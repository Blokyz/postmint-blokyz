"""Tests for app.claims.eligibility.

`test_progress_*` are pure (no DB) and always run. The `db`-fixtured tests need
Postgres (the test DB) and exercise the actual ownership/trait queries.
"""

import pytest

from app.claims.eligibility import (
    evaluate_tier,
    evaluate_wallet,
    find_tier_entry,
    matching_token_ids,
    tier_progress,
)
from app.db.models import Token, Trait

WALLET = "0x00000000000000000000000000000000000000a1"
OTHER = "0x00000000000000000000000000000000000000b2"
CONTRACT = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


# --- pure §11 progress math ---


def test_progress_below_threshold():
    assert tier_progress(2, 3) == (False, 66.67, 1)


def test_progress_exactly_meets():
    assert tier_progress(3, 3) == (True, 100.0, 0)


def test_progress_over_caps_at_100():
    assert tier_progress(5, 3) == (True, 100.0, 0)


def test_progress_zero_held():
    assert tier_progress(0, 4) == (False, 0.0, 4)


def test_progress_nonpositive_x_never_qualifies():
    assert tier_progress(10, 0) == (False, 0.0, 0)
    assert tier_progress(10, -1) == (False, 0.0, 0)


def test_find_tier_entry():
    manifest = {"tiers": [{"tier": "Common"}, {"tier": "Mythic"}]}
    assert find_tier_entry(manifest, "Mythic")["tier"] == "Mythic"
    assert find_tier_entry(manifest, "Nope") is None


# --- DB-backed ---


def _seed(db, owner_map: dict[int, str], token_traits: dict[int, list[tuple[str, str]]]):
    """owner_map: token_id -> owner. token_traits: token_id -> [(category, value)]."""
    for token_id, owner in owner_map.items():
        db.add(Token(contract_address=CONTRACT, token_id=token_id, owner_address=owner))
    for token_id, traits in token_traits.items():
        for cat, val in traits:
            db.add(Trait(contract_address=CONTRACT, token_id=token_id, trait_category=cat, trait_value=val))
    db.commit()


def _count_tier(pool, count_required, tier="Rare"):
    return {
        "tier": tier,
        "set_rule": {
            "archetype": "count_of_pool",
            "pool": [{"trait_category": c, "trait_value": v} for c, v in pool],
            "count_required": count_required,
        },
    }


def test_matching_token_ids_filters_by_owner_and_pool(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: WALLET, 3: OTHER, 4: WALLET},
        token_traits={
            1: [("Hat", "Gold")],
            2: [("Hat", "Silver")],
            3: [("Hat", "Gold")],   # owned by OTHER
            4: [("Eyes", "Laser")],  # not in pool
        },
    )
    pool = [("Hat", "Gold"), ("Hat", "Silver")]
    assert matching_token_ids(db, CONTRACT, WALLET, pool) == [1, 2]
    assert matching_token_ids(db, CONTRACT, OTHER, pool) == [3]
    assert matching_token_ids(db, CONTRACT, WALLET, []) == []


def test_evaluate_tier_qualifies(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: WALLET, 3: WALLET},
        token_traits={
            1: [("Hat", "Gold")],
            2: [("Hat", "Gold")],
            3: [("Hat", "Gold")],
        },
    )
    elig = evaluate_tier(db, CONTRACT, WALLET, _count_tier([("Hat", "Gold")], 3))
    assert elig.qualifies is True
    assert elig.held_count == 3
    assert elig.count_required == 3
    assert elig.qualifying_token_ids == [1, 2, 3]
    assert elig.progress_pct == 100.0
    assert elig.needed == 0


def test_evaluate_tier_not_qualified(db):
    _seed(db, owner_map={1: WALLET}, token_traits={1: [("Hat", "Gold")]})
    elig = evaluate_tier(db, CONTRACT, WALLET, _count_tier([("Hat", "Gold")], 3))
    assert elig.qualifies is False
    assert elig.held_count == 1
    assert elig.needed == 2
    assert elig.progress_pct == pytest.approx(33.33)


def test_evaluate_tier_apex_combo_same_as_count(db):
    _seed(db, owner_map={1: WALLET, 2: WALLET}, token_traits={1: [("Type", "XRay")], 2: [("Type", "XRay")]})
    entry = {
        "tier": "Mythic",
        "set_rule": {
            "archetype": "apex_combo",
            "pool": [{"trait_category": "Type", "trait_value": "XRay"}],
            "count_required": 2,
        },
    }
    elig = evaluate_tier(db, CONTRACT, WALLET, entry)
    assert elig.qualifies is True
    assert elig.archetype == "apex_combo"


def test_evaluate_tier_none_archetype_never_qualifies(db):
    entry = {"tier": "Empty", "set_rule": {"archetype": "none"}}
    elig = evaluate_tier(db, CONTRACT, WALLET, entry)
    assert elig.qualifies is False
    assert elig.count_required == 0


def test_evaluate_tier_one_of_each(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: WALLET},
        token_traits={1: [("Hat", "Gold")], 2: [("Eyes", "Laser")]},
    )
    entry = {
        "tier": "Legacy",
        "set_rule": {
            "archetype": "one_of_each",
            "trait_values": [
                {"trait_category": "Hat", "trait_value": "Gold"},
                {"trait_category": "Eyes", "trait_value": "Laser"},
            ],
        },
    }
    elig = evaluate_tier(db, CONTRACT, WALLET, entry)
    assert elig.qualifies is True
    assert elig.count_required == 2
    assert elig.held_count == 2
    assert elig.qualifying_token_ids == [1, 2]


def test_evaluate_wallet_all_tiers(db):
    _seed(db, owner_map={1: WALLET, 2: WALLET}, token_traits={1: [("Hat", "Gold")], 2: [("Hat", "Gold")]})
    manifest = {
        "tiers": [
            _count_tier([("Hat", "Gold")], 2, tier="Common"),
            _count_tier([("Hat", "Gold")], 5, tier="Mythic"),
        ]
    }
    results = evaluate_wallet(db, CONTRACT, WALLET, manifest)
    assert [r.tier for r in results] == ["Common", "Mythic"]
    assert results[0].qualifies is True
    assert results[1].qualifies is False
