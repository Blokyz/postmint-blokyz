"""Tests for the Phase 3 claim/race API (app.api.claims).

Uses the `client` (TestClient, get_db overridden to the test session) and `db`
fixtures from conftest. An atlas manifest is written to OUTPUT_DIR per test and
cleaned up. The backend signer key is monkeypatched onto the router settings.
"""

import pytest
from eth_account import Account

from app.api import claims as claims_mod
from app.claim_signing import backend_signer_address, recover_claim_signer
from app.db.models import Claim, Token, Trait
from app.manifests import OUTPUT_DIR, write_atlas_manifest

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
WALLET = "0x00000000000000000000000000000000000000a1"
MANAGER = "0x2222222222222222222222222222222222222222"
SIGNER_KEY = "0x" + "33" * 32
SIGNER_ADDR = Account.from_key(SIGNER_KEY).address.lower()

TIER = "Rare"


def _manifest(window_hours=72, count_required=2, cap=500):
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
    """Write an atlas manifest (window elapses immediately) and clean it up."""
    path = OUTPUT_DIR / f"{CONTRACT}_atlas_manifest.json"

    def _write(**kw):
        write_atlas_manifest(CONTRACT, _manifest(**kw))
        return path

    yield _write
    if path.exists():
        path.unlink()


def _seed_holdings(db, count, wallet=WALLET):
    for tid in range(1, count + 1):
        db.add(Token(contract_address=CONTRACT, token_id=tid, owner_address=wallet))
        db.add(Trait(contract_address=CONTRACT, token_id=tid, trait_category="Hat", trait_value="Gold"))
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


# --- submit + status ---


def test_submit_starts_window_then_status(client, db, atlas_file):
    atlas_file(window_hours=72)
    _seed_holdings(db, 2)
    r = client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 200
    assert r.json()["status"] == "racing"

    s = client.get(f"/claim/status/{CONTRACT}/{TIER}/{WALLET}")
    assert s.json()["status"] == "racing"


def test_submit_not_qualified_409(client, db, atlas_file):
    atlas_file()
    _seed_holdings(db, 1)  # need 2
    r = client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "not_qualified"
    assert r.json()["detail"]["needed"] == 1


def test_submit_unknown_tier_404(client, db, atlas_file):
    atlas_file()
    _seed_holdings(db, 2)
    r = client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": "Nope", "wallet_address": WALLET})
    assert r.status_code == 404


def test_status_not_started(client, db, atlas_file):
    atlas_file()
    _seed_holdings(db, 2)
    s = client.get(f"/claim/status/{CONTRACT}/{TIER}/{WALLET}")
    assert s.json()["status"] == "not_started"


# --- sign ---


def test_claim_sign_happy_path(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=0)  # window elapses immediately -> ready
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["manager_address"] == MANAGER
    assert body["token_ids"] == [1, 2]
    assert body["backend_signer"] == SIGNER_ADDR

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


def test_claim_sign_409_when_not_ready(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=72)  # long window -> still racing
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})

    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "racing"


def test_claim_sign_404_without_season(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=0)
    _seed_holdings(db, 2)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    r = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r.status_code == 404


def test_claim_sign_nonce_increments(client, db, atlas_file, monkeypatch):
    monkeypatch.setattr(claims_mod.settings, "backend_signer_private_key", SIGNER_KEY)
    atlas_file(window_hours=0)
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})

    n1 = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET}).json()["nonce"]
    n2 = client.post("/claim/sign", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET}).json()["nonce"]
    assert n2 > n1


# --- confirm + winners + leaderboard ---


@pytest.fixture
def mock_chain(monkeypatch):
    """Stub on-chain verification so `/claim/confirm` accepts a test tx and
    reports slot 1 (the real path fetches an eth_getTransactionReceipt)."""

    def _stub(*_a, **_k):
        return {"slot_number": 1, "nonce": 1, "window_started_at": 0}

    monkeypatch.setattr(claims_mod, "verify_claim_tx", _stub)
    return _stub


def test_confirm_records_win_and_frees_window(client, db, atlas_file, mock_chain):
    atlas_file(window_hours=0)
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})

    tx = "0x" + "ab" * 32
    r = client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": tx},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "won"
    assert r.json()["slot_number"] == 1  # authoritative slot from the on-chain event

    # The won row frees the one-active-window index: a fresh submit starts a new window.
    r2 = client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    assert r2.status_code == 200
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
    """An active window but no registered season → can't resolve a manager to verify against."""
    atlas_file(window_hours=0)
    _seed_holdings(db, 2)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
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
    atlas_file(window_hours=0)
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
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
    atlas_file(window_hours=0)
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
    r = client.post(
        "/claim/confirm",
        json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET, "tx_hash": "0x" + "77" * 32},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["retryable"] is True


def test_winners_and_leaderboard(client, db, atlas_file, mock_chain):
    atlas_file(window_hours=0, cap=3)
    _seed_holdings(db, 2)
    _register_season(client)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": TIER, "wallet_address": WALLET})
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


def test_leaderboard_404_unknown_tier(client, db, atlas_file):
    atlas_file()
    r = client.get(f"/leaderboard/{CONTRACT}/Nope")
    assert r.status_code == 404


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
