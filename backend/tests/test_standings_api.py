"""Tests for the championship-standings + driver-card aggregates (app.api.claims
/standings, /driver + app.claims.standings)."""

import pytest

from app.claims.standings import championship_points
from app.db.models import Token, Trait
from app.manifests import OUTPUT_DIR, write_atlas_manifest

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
WALLET = "0x00000000000000000000000000000000000000a1"


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


def _seed(db, count, wallet=WALLET):
    for tid in range(1, count + 1):
        db.add(Token(contract_address=CONTRACT, token_id=tid, owner_address=wallet))
        db.add(Trait(contract_address=CONTRACT, token_id=tid, trait_category="Hat", trait_value="Gold"))
    db.commit()


def _win_rare(client):
    """Submit + confirm a Rare win (window elapses immediately)."""
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": "Rare", "wallet_address": WALLET})
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
    _win_rare(client)
    body = client.get(f"/standings/{CONTRACT}").json()
    rare = next(t for t in body["tiers"] if t["tier"] == "Rare")
    assert rare["slots_filled"] == 1
    assert rare["slots_remaining"] == 499
    assert len(body["collectors"]) == 1
    c = body["collectors"][0]
    assert c["wallet_address"] == WALLET
    assert c["championship_points"] == 15
    assert c["badges_won"] == 1
    assert c["rank"] == 1


def test_standings_404_without_manifest(client):
    r = client.get(f"/standings/{CONTRACT}")
    assert r.status_code == 404


# --- /driver ---


def test_driver_states_won_and_locked(client, db, atlas_file):
    _seed(db, 2)  # holds 2 -> qualifies Rare (need 2), not Mythic (need 3)
    _win_rare(client)
    body = client.get(f"/driver/{CONTRACT}/{WALLET}").json()
    assert body["championship_points"] == 15
    assert body["badges_won"] == 1
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert tiers["Rare"]["state"] == "won"
    assert tiers["Rare"]["slot_numbers"] == [1]
    assert tiers["Mythic"]["state"] == "locked"
    assert tiers["Mythic"]["needed"] == 1


def test_driver_qualified_state_before_window(client, db, atlas_file):
    _seed(db, 2)  # qualifies Rare, no window started
    body = client.get(f"/driver/{CONTRACT}/{WALLET}").json()
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert tiers["Rare"]["state"] == "qualified"
    assert body["championship_points"] == 0


def test_driver_racing_state(client, db, atlas_file):
    # A long window keeps Rare racing after submit.
    write_atlas_manifest(
        CONTRACT,
        {
            **_manifest(),
            "tier_structure": {"Rare": {"cap": 500, "holding_window_hours": 72}, "Mythic": {"cap": 50, "holding_window_hours": 0}},
        },
    )
    _seed(db, 2)
    client.post("/claim/submit", json={"contract_address": CONTRACT, "tier": "Rare", "wallet_address": WALLET})
    body = client.get(f"/driver/{CONTRACT}/{WALLET}").json()
    tiers = {t["tier"]: t for t in body["tiers"]}
    assert tiers["Rare"]["state"] == "racing"
