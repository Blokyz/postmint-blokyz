"""Tests for the Phase 3 claim/race API (app.api.claims).

Uses the `client` (TestClient, get_db overridden to the test session) and `db`
fixtures from conftest. An atlas manifest is written to OUTPUT_DIR per test and
cleaned up. The backend signer key is monkeypatched onto the router settings.

Windows are DERIVED from `tokens.acquired_at` (no submit/opt-in): seeding
old acquisitions makes a wallet `ready`, recent ones `racing`. Holdings are
always seeded with a non-NULL acquired_at so the lazy Moralis backfill never
fires in these tests.
"""

import datetime as dt

import pytest
from eth_account import Account

from app.api import claims as claims_mod
from app.claim_signing import backend_signer_address, recover_claim_signer
from app.db.models import Claim, Token, Trait
from app.manifests import write_atlas_manifest

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
WALLET = "0x00000000000000000000000000000000000000a1"
MANAGER = "0x2222222222222222222222222222222222222222"
SIGNER_KEY = "0x" + "33" * 32
SIGNER_ADDR = Account.from_key(SIGNER_KEY).address.lower()

TIER = "Rare"

LONG_AGO = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)
JUST_NOW = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)


def _manifest(window_hours=24, count_required=2, cap=500):
    return {
        "tier_structure": {TIER: {"cap": cap, "holding_window_hours": window_hours}},
        "tiers": [
            {
                "tier": TIER,
                "set_rule": {
                    "archetype": "count_of_pool",
                    "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
                    "count_required": count_required,
                },
            }
        ],
    }


@pytest.fixture
def atlas_file():
    """Write an atlas manifest (cleaned up by the manifests-table truncate)."""

    def _write(**kw):
        write_atlas_manifest(CONTRACT, _manifest(**kw))

    return _write


def _seed_holdings(db, count, wallet=WALLET, acquired_at=LONG_AGO, start_id=1):
    for tid in range(start_id, start_id + count):
        db.add(
            Token(
                contract_address=CONTRACT, token_id=tid, owner_address=wallet, acquired_at=acquired_at
            )
        )
        db.add(Trait(contract_address=CONTRACT, token_id=tid, trait_category="Hat", trait_value="Gold"))
    db.commit()


def _seed_signed_row(db, wallet=WALLET, tokens=(1, 2)):
    """A claims row as /claim/sign leaves it (window recorded, not yet won)."""
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier=TIER,
            wallet_address=wallet,
            window_started=LONG_AGO,
            qualifying_tokens=list(tokens),
        )
    )
    db.commit()


def _register_season(client):
    return client.post(
        "/claims/season",
        json={"contract_address": CONTRACT, "manager_address": MANAGER},
    )


# --- eligibility ---


def test_eligibility_reports_qualification(client, db, atlas_file):
    atlas_file()
    _seed_holdings(db, 2)
    r = client.get(f"/eligibility/{CONTRACT}/{WALLET}")
    assert r.status_code == 200
    tier = r.json()["tiers"][0]
    assert tier["tier"] == TIER
    assert tier["qualifies"] is True
    assert tier["held_count"] == 2


def test_eligibility_404_without_manifest(client):
    r = client.get(f"/eligibility/{CONTRACT}/{WALLET}")
    assert r.status_code == 404


# --- derived window status ---


def test_status_long_holder_is_ready(client, db, atlas_file):
    """Held the set for 48h against a 24h window -> ready on first load."""
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    s = client.get(f"/claim/status/{CONTRACT}/{TIER}/{WALLET}")
    assert s.json()["status"] == "ready"
    assert s.json()["window_started"] == LONG_AGO.isoformat()


def test_status_fresh_buyer_is_racing(client, db, atlas_file):
    """Completed the set 1h ago -> auto countdown, no opt-in needed."""
    atlas_file(window_hours=24)
    _seed_holdings(db, 2, acquired_at=JUST_NOW)
    s = client.get(f"/claim/status/{CONTRACT}/{TIER}/{WALLET}")
    body = s.json()
    assert body["status"] == "racing"
    assert 0 < body["seconds_remaining"] <= 23 * 3600


def test_status_not_qualified(client, db, atlas_file):
    atlas_file()
    _seed_holdings(db, 1)  # need 2
    s = client.get(f"/claim/status/{CONTRACT}/{TIER}/{WALLET}")
    assert s.json()["status"] == "not_started"
    assert s.json()["qualifies"] is False


def test_status_unknown_tier_404(client, db, atlas_file):
    atlas_file()
    _seed_holdings(db, 2)
    r = client.get(f"/claim/status/{CONTRACT}/Nope/{WALLET}")
    assert r.status_code == 404


# --- sign ---


def test_claim_sign_happy_path(client, db, atlas_file, monkeypatch):
    """A long holder signs with windowStartedAt = the set-completion moment,
    and the sign records the claim row for /claim/confirm."""
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)  # acquired 48h ago -> ready
    _register_season(client)

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["manager_address"] == MANAGER
    assert body["token_ids"] == [1, 2]
    assert body["backend_signer"] == SIGNER_ADDR
    # The attested window start is the acquisition-derived completion time.
    assert body["window_started_at"] == int(LONG_AGO.timestamp())

    recovered = recover_claim_signer(
        body["chain_id"],
        body["manager_address"],
        CONTRACT,
        WALLET,
        TIER,
        body["token_ids"],
        body["window_started_at"],
        body["expiry"],
        body["nonce"],
        body["signature"],
    )
    assert recovered == SIGNER_ADDR
    # Sign created the claim row (there is no submit step anymore).
    row = db.query(Claim).one()
    assert row.on_chain_tx_hash is None
    assert row.qualifying_tokens == [1, 2]


def test_claim_sign_binds_exactly_one_set(client, db, atlas_file, monkeypatch):
    """A holder with MORE than count_required tokens signs with exactly the
    count_required OLDEST-held ones — never the whole holding (only the signed
    set is consumed on the win, so the surplus keeps racing)."""
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    older = LONG_AGO - dt.timedelta(hours=24)  # 72h ago
    _seed_holdings(db, 2, acquired_at=LONG_AGO, start_id=1)   # 48h ago
    _seed_holdings(db, 2, acquired_at=older, start_id=3)      # 72h ago (oldest)
    _register_season(client)

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 200, r.text
    assert r.json()["token_ids"] == [3, 4]  # the two oldest, not all four
    assert db.query(Claim).one().qualifying_tokens == [3, 4]


def test_whale_sweeps_with_disjoint_sets(client, db, atlas_file, mock_chain, monkeypatch):
    """6 tokens on a 2-set tier = 3 claims: each win consumes exactly one set
    and the remaining tokens keep qualifying (the user-reported 6/2 case)."""
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24, cap=5)
    _seed_holdings(db, 6)
    _register_season(client)

    # Each confirm lands a distinct on-chain slot (the shared stub always says
    # slot 1, which would trip the unique (contract, tier, slot) index here).
    slot_counter = {"n": 0}

    def _next_slot(*_a, **_k):
        slot_counter["n"] += 1
        return {"slot_number": slot_counter["n"], "nonce": slot_counter["n"], "window_started_at": 0}

    monkeypatch.setattr(claims_mod, "verify_claim_tx", _next_slot)

    expected_sets = ([1, 2], [3, 4], [5, 6])
    for i, expected in enumerate(expected_sets):
        r = client.post(
            "/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET}
        )
        assert r.status_code == 200, f"claim {i + 1}: {r.text}"
        assert r.json()["token_ids"] == expected
        r = client.post(
            "/claim/confirm",
            json={
                "contract_address": CONTRACT,
                "tier": TIER,
                "wallet_address": WALLET,
                "tx_hash": "0x" + f"{i:02x}" * 32,
            },
        )
        assert r.status_code == 200

        left = client.get(f"/eligibility/{CONTRACT}/{WALLET}").json()["tiers"][0]
        assert left["held_count"] == 6 - 2 * (i + 1)

    # All three sets spent — a fourth claim is refused.
    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "not_started"


def test_claim_sign_zero_window_instant(client, db, atlas_file, monkeypatch):
    """Common-style tier: freshly acquired (even unstamped) tokens sign
    immediately with a just-past windowStartedAt."""
    import time

    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=0)
    _seed_holdings(db, 2, acquired_at=None)  # acquisition data never consulted
    _register_season(client)

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 200, r.text
    # Back-dated ~60s so chain clock skew can't fail the elapsed check.
    assert 0 < int(time.time()) - r.json()["window_started_at"] <= 120


def test_claim_sign_409_when_not_ready(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2, acquired_at=JUST_NOW)  # completed 1h ago -> racing
    _register_season(client)

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "racing"
    # No claim row is recorded for a refused sign.
    assert db.query(Claim).count() == 0


def test_claim_sign_409_when_not_qualified(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    _seed_holdings(db, 1)  # need 2
    _register_season(client)

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "not_started"


def test_claim_sign_404_without_season(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 404


def test_claim_sign_nonce_increments(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    _register_season(client)

    n1 = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET}).json()["nonce"]
    n2 = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET}).json()["nonce"]
    assert n2 > n1
    # Re-signs reuse the one active claim row, not stack new ones.
    assert db.query(Claim).count() == 1


def test_claim_sign_locks_active_claim(client, db, atlas_file, monkeypatch):
    """Verify that _active_claim is invoked with for_update=True during claim signing."""
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    _register_season(client)

    called_for_update = []
    orig_active_claim = claims_mod._active_claim

    def spy_active_claim(db_sess, contract, tier, wallet, for_update=False):
        called_for_update.append(for_update)
        return orig_active_claim(db_sess, contract, tier, wallet, for_update=for_update)

    monkeypatch.setattr(claims_mod, "_active_claim", spy_active_claim)

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 200, r.text
    assert True in called_for_update


# --- confirm + winners + leaderboard ---


def test_confirm_records_win_and_frees_window(client, db, atlas_file, mock_chain, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})

    tx = "0x" + "ab" * 32
    r = client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": tx},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "won"
    assert r.json()["slot_number"] == 1  # authoritative slot from the on-chain event

    # Set consumption (2026-08-05): the winning set is SPENT for this tier — a
    # re-sign with the same tokens is refused (the wallet no longer qualifies).
    r2 = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r2.status_code == 409
    assert r2.json()["detail"]["status"] == "not_started"

    # A fresh DISJOINT set qualifies again (whales may sweep, but never with the
    # same tokens): the new sign uses only the unspent token ids.
    _seed_holdings(db, 2, start_id=11)
    r3 = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r3.status_code == 200
    assert r3.json()["token_ids"] == [11, 12]
    assert db.query(Claim).count() == 2


def test_confirm_404_without_active_window(client, db, atlas_file):
    atlas_file()
    tx = "0x" + "cd" * 32
    r = client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": tx},
    )
    assert r.status_code == 404


def test_confirm_404_without_registered_season(client, db, atlas_file):
    """An active claim row but no registered season → can't resolve a manager to verify against."""
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    _seed_signed_row(db)
    r = client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": "0x" + "ab" * 32},
    )
    assert r.status_code == 404
    assert "season" in r.json()["detail"].lower()


def test_confirm_400_on_spoofed_tx(client, db, atlas_file, monkeypatch):
    """A tx that doesn't carry a matching Claimed event is rejected (spoof guard)."""
    from app.claims.onchain import ClaimVerificationError

    def _reject(*_a, **_k):
        raise ClaimVerificationError("no matching Claimed event for this wallet + tier")

    monkeypatch.setattr(claims_mod, "verify_claim_tx", _reject)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    _register_season(client)
    _seed_signed_row(db)
    r = client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": "0x" + "99" * 32},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_claim_tx"
    # The window is NOT marked won.
    assert db.query(Claim).filter(Claim.on_chain_tx_hash.isnot(None)).count() == 0


def test_confirm_409_when_tx_not_mined(client, db, atlas_file, monkeypatch):
    """Receipt not yet available → retryable 409, window left open."""
    from app.claims.onchain import ReceiptNotFound

    def _pending(*_a, **_k):
        raise ReceiptNotFound("transaction receipt not available yet")

    monkeypatch.setattr(claims_mod, "verify_claim_tx", _pending)
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    _register_season(client)
    _seed_signed_row(db)
    r = client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": "0x" + "77" * 32},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["retryable"] is True


def test_winners_and_leaderboard(client, db, atlas_file, mock_chain):
    atlas_file(window_hours=24, cap=3)
    _seed_holdings(db, 2)
    _register_season(client)
    _seed_signed_row(db)
    tx = "0x" + "ef" * 32
    client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": tx},
    )

    w = client.get(f"/winners/{CONTRACT}")
    assert w.status_code == 200
    assert w.json()["total"] == 1
    assert w.json()["winners_by_tier"][TIER][0]["wallet_address"] == WALLET

    lb = client.get(f"/leaderboard/{CONTRACT}/{TIER}")
    assert lb.status_code == 200
    body = lb.json()
    assert body["cap"] == 3
    assert body["slots_filled"] == 1
    assert body["slots_remaining"] == 2
    assert body["winners"][0]["slot_number"] == 1
    # The winning set is consumed for this tier — the winner is no longer a
    # racer until it assembles a fresh disjoint set.
    assert body["racers"] == []
    assert body["total_racers"] == 0

    # Two fresh tokens re-qualify the wallet as a racer.
    _seed_holdings(db, 2, start_id=11)
    body = client.get(f"/leaderboard/{CONTRACT}/{TIER}").json()
    assert body["racers"] == [{"wallet_address": WALLET, "held_count": 2, "status": "qualified"}]


def test_race_state_batches_lanes(client, db, atlas_file, mock_chain):
    """One /race-state call returns per-tier elig + derived window + leaderboard,
    with winners capped and the wallet's own wins surfaced separately."""
    atlas_file(window_hours=24, cap=3)
    _seed_holdings(db, 2)  # long-held set -> ready

    r = client.get(f"/race-state/{CONTRACT}/{WALLET}")
    assert r.status_code == 200
    body = r.json()
    assert body["wallet_address"] == WALLET
    assert len(body["lanes"]) == 1
    lane = body["lanes"][0]
    assert lane["elig"]["tier"] == TIER
    assert lane["elig"]["qualifies"] is True
    assert lane["ws"]["status"] == "ready"  # derived from acquisition history
    assert lane["lb"]["cap"] == 3
    assert lane["lb"]["my_wins"] == []  # nothing won yet


def test_race_state_my_wins_survives_winner_cap(client, db, atlas_file):
    """my_wins is computed before the 5-winner cap, so a wallet's win outside
    the podium is still reported."""
    atlas_file(window_hours=24, cap=10)
    # 6 other winners in slots 1-6 (fill the podium), then WALLET in slot 7.
    for i in range(6):
        db.add(
            Claim(
                contract_address=CONTRACT, tier=TIER, wallet_address=f"0x{i:040x}",
                qualifying_tokens=[100 + i], on_chain_tx_hash=f"0x{i:064x}", slot_number=i + 1,
            )
        )
    db.add(
        Claim(
            contract_address=CONTRACT, tier=TIER, wallet_address=WALLET,
            qualifying_tokens=[7], on_chain_tx_hash="0x" + "cd" * 32, slot_number=7,
        )
    )
    db.commit()

    lane = client.get(f"/race-state/{CONTRACT}/{WALLET}").json()["lanes"][0]
    assert len(lane["lb"]["winners"]) == 5  # podium capped
    assert lane["lb"]["slots_filled"] == 7  # count is total, not the cap
    assert [w["slot_number"] for w in lane["lb"]["my_wins"]] == [7]


def test_leaderboard_404_unknown_tier(client, db, atlas_file):
    atlas_file()
    r = client.get(f"/leaderboard/{CONTRACT}/Nope")
    assert r.status_code == 404


def test_leaderboard_racers_pagination(client, db, atlas_file):
    """Racers = qualified wallets, ranked by held count then address;
    total_racers reports the full count."""
    atlas_file(window_hours=24)
    for i in range(5):
        _seed_holdings(db, 2, wallet=f"0x{i:040x}", start_id=1 + i * 2)

    body = client.get(f"/leaderboard/{CONTRACT}/{TIER}?racers_limit=2").json()
    assert body["total_racers"] == 5
    assert [r["wallet_address"] for r in body["racers"]] == [f"0x{i:040x}" for i in range(2)]

    page2 = client.get(f"/leaderboard/{CONTRACT}/{TIER}?racers_limit=2&racers_offset=2").json()
    assert [r["wallet_address"] for r in page2["racers"]] == [f"0x{i:040x}" for i in range(2, 4)]


def test_leaderboard_racers_exclude_consumed_sets(client, db, atlas_file):
    """A wallet whose whole qualifying set was spent on a won claim stops
    counting as a racer until it assembles a fresh set."""
    atlas_file(window_hours=24)
    _seed_holdings(db, 2)
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier=TIER,
            wallet_address=WALLET,
            qualifying_tokens=[1, 2],
            on_chain_tx_hash="0x" + "ab" * 32,
            slot_number=1,
        )
    )
    db.commit()

    body = client.get(f"/leaderboard/{CONTRACT}/{TIER}").json()
    assert body["slots_filled"] == 1
    assert body["total_racers"] == 0  # both held tokens are consumed for this tier


# --- season register ---


def test_register_season_idempotent(client, db):
    r1 = _register_season(client)
    assert r1.status_code == 200
    assert r1.json()["manager_address"] == MANAGER
    r2 = _register_season(client)
    assert r2.status_code == 200
    from app.db.models import Season

    assert db.query(Season).count() == 1


def test_register_season_requires_token_when_configured(client, db, monkeypatch):
    """With operator_api_token set, the platform bearer token is required."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "operator_api_token", "s3cret")
    assert _register_season(client).status_code == 401  # no token
    ok = client.post(
        "/claims/season",
        json={"contract_address": CONTRACT, "manager_address": MANAGER},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert ok.status_code == 200
