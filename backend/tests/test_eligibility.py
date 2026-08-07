"""Tests for app.claims.eligibility.

`test_progress_*` are pure (no DB) and always run. The `db`-fixtured tests need
Postgres (the test DB) and exercise the actual ownership/trait queries.
"""

import pytest

from app.claims.eligibility import (
    consumed_token_ids,
    evaluate_tier,
    evaluate_wallet,
    find_tier_entry,
    matching_token_ids,
    pool_traits_with_rarity,
    shopping_guidance_for_wallet,
    tier_progress,
    unowned_candidate_tokens,
)
from app.db.models import Claim, Token, Trait

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


def test_unowned_candidate_tokens(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: OTHER, 3: OTHER},
        token_traits={
            1: [("Hat", "Gold")],
            2: [("Hat", "Gold")],
            3: [("Hat", "Silver")],
        },
    )
    pool = [("Hat", "Gold"), ("Hat", "Silver")]
    candidates = unowned_candidate_tokens(db, CONTRACT, WALLET, pool)
    assert candidates == [2, 3]


def test_pool_traits_with_rarity(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: OTHER, 3: OTHER},
        token_traits={
            1: [("Hat", "Gold")],
            2: [("Hat", "Gold")],
            3: [("Hat", "Silver")],
        },
    )
    pool = [("Hat", "Silver"), ("Hat", "Gold")]
    traits = pool_traits_with_rarity(db, CONTRACT, pool)
    # Gold has 2 occurrences, Silver has 1 — Gold should be first
    assert traits[0]["trait_value"] == "Gold"
    assert traits[0]["token_count"] == 2
    assert traits[1]["trait_value"] == "Silver"
    assert traits[1]["token_count"] == 1


# --- set consumption (2026-08-05): tokens behind a WON claim are spent per tier ---


def _won_claim(db, tier, wallet, tokens, tx="0x" + "ab" * 32, slot=1):
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier=tier,
            wallet_address=wallet,
            qualifying_tokens=tokens,
            on_chain_tx_hash=tx,
            slot_number=slot,
        )
    )
    db.commit()


def test_won_claim_consumes_set_for_that_tier(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: WALLET},
        token_traits={1: [("Hat", "Gold")], 2: [("Hat", "Gold")]},
    )
    entry = _count_tier([("Hat", "Gold")], 2)
    assert evaluate_tier(db, CONTRACT, WALLET, entry).qualifies is True

    _won_claim(db, "Rare", WALLET, [1, 2])
    elig = evaluate_tier(db, CONTRACT, WALLET, entry)
    assert elig.qualifies is False
    assert elig.held_count == 0
    assert elig.qualifying_token_ids == []
    assert elig.needed == 2


def test_consumption_is_per_tier_not_cross_tier(db):
    _seed(db, owner_map={1: WALLET}, token_traits={1: [("Hat", "Gold")]})
    _won_claim(db, "Rare", WALLET, [1])
    # Same token still qualifies the wallet in a DIFFERENT tier.
    other = _count_tier([("Hat", "Gold")], 1, tier="Common")
    assert evaluate_tier(db, CONTRACT, WALLET, other).qualifies is True


def test_consumption_follows_token_across_transfer(db):
    # WALLET won with token 1, then sold it to OTHER — OTHER can't reuse it here.
    _seed(db, owner_map={1: OTHER}, token_traits={1: [("Hat", "Gold")]})
    _won_claim(db, "Rare", WALLET, [1])
    elig = evaluate_tier(db, CONTRACT, OTHER, _count_tier([("Hat", "Gold")], 1))
    assert elig.qualifies is False


def test_unconfirmed_sign_row_does_not_consume(db):
    _seed(db, owner_map={1: WALLET}, token_traits={1: [("Hat", "Gold")]})
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier="Rare",
            wallet_address=WALLET,
            qualifying_tokens=[1],
            on_chain_tx_hash=None,  # signed but never landed
        )
    )
    db.commit()
    assert consumed_token_ids(db, CONTRACT, "Rare") == set()
    assert evaluate_tier(db, CONTRACT, WALLET, _count_tier([("Hat", "Gold")], 1)).qualifies is True


def test_fresh_disjoint_set_qualifies_again(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: WALLET, 3: WALLET, 4: WALLET},
        token_traits={n: [("Hat", "Gold")] for n in (1, 2, 3, 4)},
    )
    _won_claim(db, "Rare", WALLET, [1, 2])
    elig = evaluate_tier(db, CONTRACT, WALLET, _count_tier([("Hat", "Gold")], 2))
    assert elig.qualifies is True
    assert elig.qualifying_token_ids == [3, 4]  # only the unspent tokens


def test_shopping_guidance_for_wallet(db):
    _seed(
        db,
        owner_map={1: WALLET, 2: OTHER, 3: OTHER},
        token_traits={
            1: [("Hat", "Gold")],
            2: [("Hat", "Gold")],
            3: [("Hat", "Gold"), ("Background", "Blue")],
        },
    )
    manifest = {
        "tiers": [
            _count_tier([("Hat", "Gold")], 1, tier="Common"),
            _count_tier([("Hat", "Gold")], 3, tier="Super Rare"),
            _count_tier([("Hat", "Gold"), ("Background", "Blue")], 3, tier="Mythic"),
        ]
    }
    guidance = shopping_guidance_for_wallet(db, CONTRACT, WALLET, manifest, chain="base")
    assert guidance["chain"] == "base"
    # Common is qualified (held 1, needed 0) so it shouldn't be in short_tiers
    tier_names = [st["tier"] for st in guidance["short_tiers"]]
    assert "Common" not in tier_names
    assert "Super Rare" in tier_names
    assert "Mythic" in tier_names

    sr = next(st for st in guidance["short_tiers"] if st["tier"] == "Super Rare")
    assert sr["needed"] == 2
    assert sr["candidate_token_ids"] == [2, 3]
    # Check cross tier impact on Mythic
    assert len(sr["cross_tier_impact"]) > 0
    assert sr["cross_tier_impact"][0]["tier"] == "Mythic"

