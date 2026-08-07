"""Tests for the championship-standings + driver-card aggregates (app.api.claims
/standings, /driver + app.claims.standings).

Windows are derived from `tokens.acquired_at` — holdings are seeded with a
non-NULL acquired_at so the lazy Moralis backfill never fires."""

import datetime as dt

import pytest

from app.claims.standings import championship_points
from app.db.models import Claim, Token, Trait
from app.manifests import OUTPUT_DIR, write_atlas_manifest

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
WALLET = "0x00000000000000000000000000000000000000a1"

LONG_AGO = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)


def _manifest():
    # Two tiers: Rare (need 2, count_of_pool on Hat=Gold) and Mythic (need 3).
    return {
        "tier_structure": {
            "Rare": {"cap": 500, "holding_window_hours": 0},
            "Mythic": {"cap": 50, "holding_window_hours": 0},
        },
        "tiers": [
            {
                "tier": "Rare",
                "set_rule": {
                    "archetype": "count_of_pool",
                    "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
                    "count_required": 2,
                },
            },
            {
                "tier": "Mythic",
                "set_rule": {
                    "archetype": "apex_combo",
                    "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
                    "count_required": 3,
                },
            },
        ],
    }


@pytest.fixture
def atlas_file():
    path = OUTPUT_DIR / f"{CONTRACT}_atlas_manifest.json"
    write_atlas_manifest(CONTRACT, _manifest())
    yield
    if path.exists():
        path.unlink()


def _seed(db, count, wallet=WALLET, acquired_at=LONG_AGO):
    for tid in range(1, count + 1):
        db.add(
            Token(
                contract_address=CONTRACT, token_id=tid, owner_address=wallet, acquired_at=acquired_at
            )
        )
        db.add(Trait(contract_address=CONTRACT, token_id=tid, trait_category="Hat", trait_value="Gold"))
    db.commit()


@pytest.fixture(autouse=True)
def _mock_chain(mock_chain):
    """Every test here may confirm claims — apply the conftest stub throughout."""


def _win_rare(client, db):
    """Record a signed claim row + confirm a Rare win (mock-chain verified)."""
    client.post("/claims/season", json={"contract_address": CONTRACT, "manager_address": "0x" + "11" * 20})
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier="Rare",
            wallet_address=WALLET,
            window_started=LONG_AGO,
            qualifying_tokens=[1, 2],
        )
    )
    db.commit()
    client.post(
        "/claim/confirm",
        json={
            "contract_address": CONTRACT,
            "tier": "Rare",
            "wallet_address": WALLET,
            "tx_hash": "0x" + "ab" * 32,
            "slot_number": 1,
        },
    )



# --- championship_points ---


def test_championship_points_known_and_ramp():
    assert championship_points("Rare", 2) == 15
    assert championship_points("Mythic", 4) == 50
    # Unknown tier name falls back to the ramp by index.
    assert championship_points("Weird", 0) == 5
    assert championship_points("Weird", 99) == 50


# --- /standings ---


def test_standings_empty_grid(client, db, atlas_file):
    _seed(db, 2)
    r = client.get(f"/standings/{CONTRACT}")
    assert r.status_code == 200
    body = r.json()
    assert [t["tier"] for t in body["tiers"]] == ["Rare", "Mythic"]
    assert body["tiers"][0]["slots_filled"] == 0
    assert body["collectors"] == []


def test_standings_ranks_collector_after_win(client, db, atlas_file):
    _seed(db, 2)  # qualifies Rare
    _win_rare(client, db)
    body = client.get(f"/standings/{CONTRACT}").json()
    rare = next(t for t in body["tiers"] if t["tier"] == "Rare")
    assert rare["slots_filled"] == 1
    assert rare["slots_remaining"] == 499
    assert rare["racers"] == 0  # the winning set is consumed for this tier
    assert len(body["collectors"]) == 1
    c = body["collectors"][0]
    assert c["wallet_address"] == WALLET
    assert c["championship_points"] == 15
    assert c["badges_won"] == 1
    assert c["rank"] == 1


def test_standings_404_without_manifest(client):
    r = client.get(f"/standings/{CONTRACT}")
    assert r.status_code == 404


def test_standings_uses_cache_and_invalidates_on_confirm(client, db, atlas_file, monkeypatch):
    """With a TTL set, repeat GETs are served from cache; a claim mutation
    invalidates so the win shows up immediately."""
    from app.api import claims as claims_mod

    _seed(db, 2)
    monkeypatch.setattr(claims_mod.settings, "standings_cache_ttl_seconds", 60)

    calls = []
    orig = claims_mod.build_standings

    def spy(*a, **kw):
        calls.append(1)
        return orig(*a, **kw)

    monkeypatch.setattr(claims_mod, "build_standings", spy)

    client.get(f"/standings/{CONTRACT}")
    client.get(f"/standings/{CONTRACT}")
    assert len(calls) == 1  # second GET was a cache hit

    _win_rare(client, db)  # confirm invalidates
    body = client.get(f"/standings/{CONTRACT}").json()
    assert len(calls) == 2  # rebuilt after invalidation
    rare = next(t for t in body["tiers"] if t["tier"] == "Rare")
    assert rare["slots_filled"] == 1


def _seed_won_row(db, wallet, slot):
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier="Rare",
            wallet_address=wallet,
            on_chain_tx_hash="0x" + f"{slot:064x}",
            slot_number=slot,
        )
    )


def test_standings_collectors_pagination(client, db, atlas_file):
    for i in range(3):
        _seed_won_row(db, f"0x{i:040x}", slot=i + 1)
    db.commit()

    body = client.get(f"/standings/{CONTRACT}?limit=2").json()
    assert body["total_collectors"] == 3
    assert len(body["collectors"]) == 2

    page2 = client.get(f"/standings/{CONTRACT}?limit=2&offset=2").json()
    assert len(page2["collectors"]) == 1
    # Rank is assigned over the full CP-ranked list, so page 2 keeps global rank.
    assert page2["collectors"][0]["rank"] == 3


# --- /driver ---


def test_driver_states_won_and_locked(client, db, atlas_file):
    _seed(db, 2)  # holds 2 -> qualifies Rare (need 2), not Mythic (need 3)
    _win_rare(client, db)
    body = client.get(f"/driver/{CONTRACT}/{WALLET}").json()
    assert body["championship_points"] == 15
    assert body["badges_won"] == 1
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert tiers["Rare"]["state"] == "won"
    assert tiers["Rare"]["slot_numbers"] == [1]
    assert tiers["Mythic"]["state"] == "locked"
    assert tiers["Mythic"]["needed"] == 1


def test_driver_ready_state_zero_window(client, db, atlas_file):
    """Qualification on a zero-window tier is immediately ready (no opt-in)."""
    _seed(db, 2)  # qualifies Rare (window 0)
    body = client.get(f"/driver/{CONTRACT}/{WALLET}").json()
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert tiers["Rare"]["state"] == "ready"
    assert body["championship_points"] == 0


def test_driver_ready_and_racing_derive_from_acquisitions(client, db, atlas_file):
    """With a 24h window: a long holder is ready, a fresh buyer is racing."""
    write_atlas_manifest(
        CONTRACT,
        {
            **_manifest(),
            "tier_structure": {"Rare": {"cap": 500, "holding_window_hours": 24}, "Mythic": {"cap": 50, "holding_window_hours": 0}},
        },
    )
    _seed(db, 2)  # acquired 48h ago -> ready
    body = client.get(f"/driver/{CONTRACT}/{WALLET}").json()
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert tiers["Rare"]["state"] == "ready"

    # Rebuy: token 2 restamped 1h ago -> set completed 1h ago -> racing.
    db.get(Token, (CONTRACT, 2)).acquired_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    db.commit()
    body = client.get(f"/driver/{CONTRACT}/{WALLET}").json()
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert tiers["Rare"]["state"] == "racing"
