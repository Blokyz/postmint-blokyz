"""Tests for the Set Atlas generator (backend/app/atlas/) and /atlas API routes."""

import uuid

import pytest

from app.atlas.bands import TIER_ORDER, slice_into_tiers
from app.atlas.generator import DEFAULT_TIER_STRUCTURE, TIER_OUTPUT_ORDER
from app.atlas.pools import pool_token_count, wallet_counts_for_pool, wallet_owners_for_trait
from app.atlas.rules import build_tier, detect_ladders, feasibility
from app.db.models import IngestJob, Token, Trait
from app.manifests import load_atlas_manifest, write_ranking_manifest

_CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f99e"


# ── bands.slice_into_tiers ──────────────────────────────────────────────────

def _ranked(n: int) -> list[dict]:
    return [
        {"rank": i + 1, "trait_category": "Trait", "trait_value": f"v{i+1}", "combined_score": 1.0 - i * 1e-6}
        for i in range(n)
    ]


def test_slice_into_tiers_full_coverage_1000():
    tiers = slice_into_tiers(_ranked(1000))
    sizes = {t: len(v) for t, v in tiers.items()}
    assert sizes == {
        "Mythic": 70, "Super Rare": 80, "Rare": 150, "Uncommon": 200, "Common": 500,
    }
    assert sum(sizes.values()) == 1000

    all_ranks = [t["rank"] for tier in TIER_ORDER for t in tiers[tier]]
    assert all_ranks == list(range(1, 1001))


def test_slice_into_tiers_small_n():
    tiers = slice_into_tiers(_ranked(5))
    sizes = {t: len(v) for t, v in tiers.items()}
    assert sum(sizes.values()) == 5
    assert sizes["Mythic"] == 1
    assert sizes["Common"] == 2


def test_slice_into_tiers_empty():
    tiers = slice_into_tiers([])
    assert all(v == [] for v in tiers.values())


# ── pools.py ─────────────────────────────────────────────────────────────────

def _add_token(db, token_id: int, owner: str) -> None:
    db.add(Token(contract_address=_CONTRACT, token_id=token_id, owner_address=owner))


def _add_trait(db, token_id: int, category: str, value: str) -> None:
    db.add(Trait(contract_address=_CONTRACT, token_id=token_id, trait_category=category, trait_value=value))


def test_pool_token_count(db):
    for tid in range(1, 4):
        _add_token(db, tid, f"0xwallet{tid}")
        _add_trait(db, tid, "Background", "Red")
    _add_token(db, 4, "0xwallet4")
    _add_trait(db, 4, "Background", "Blue")
    db.commit()

    assert pool_token_count(db, _CONTRACT, [("Background", "Red")]) == 3
    assert pool_token_count(db, _CONTRACT, [("Background", "Blue")]) == 1
    assert pool_token_count(db, _CONTRACT, []) == 0


def test_wallet_counts_for_pool(db):
    _add_token(db, 1, "0xA")
    _add_trait(db, 1, "Background", "Red")
    _add_token(db, 2, "0xA")
    _add_trait(db, 2, "Background", "Red")
    _add_token(db, 3, "0xB")
    _add_trait(db, 3, "Background", "Red")
    db.commit()

    counts = wallet_counts_for_pool(db, _CONTRACT, [("Background", "Red")])
    assert counts == {"0xA": 2, "0xB": 1}
    assert wallet_counts_for_pool(db, _CONTRACT, []) == {}


def test_wallet_owners_for_trait(db):
    _add_token(db, 1, "0xA")
    _add_trait(db, 1, "Background", "Red")
    _add_token(db, 2, "0xA")
    _add_trait(db, 2, "Eyes", "Laser")
    _add_token(db, 3, "0xB")
    _add_trait(db, 3, "Background", "Red")
    db.commit()

    assert wallet_owners_for_trait(db, _CONTRACT, "Background", "Red") == {"0xA", "0xB"}
    assert wallet_owners_for_trait(db, _CONTRACT, "Eyes", "Laser") == {"0xA"}
    assert wallet_owners_for_trait(db, _CONTRACT, "Eyes", "Nonexistent") == set()


# ── rules.feasibility ──────────────────────────────────────────────────────

def test_feasibility_basic():
    # fit_score is now the over-subscription ratio (qualifiers/cap), not 1/|log|.
    f = feasibility(pool_qty=10, estimated_qualifiers=5, cap=10, x=2)
    assert f["max_sets_formable"] == 5
    assert f["race_intensity"] == 0.5
    assert f["fit_score"] == 0.5  # equals race_intensity by construction


def test_feasibility_oversubscribed_in_band():
    # cap=3, 9 qualifiers -> ratio 3.0, squarely in the healthy [2, 5] band.
    f = feasibility(pool_qty=20, estimated_qualifiers=9, cap=3, x=1)
    assert f["race_intensity"] == 3.0
    assert f["fit_score"] == 3.0


def test_feasibility_zero_qualifiers_is_zero_fit():
    # No qualifiers -> ratio 0.0 (defined, and below the healthy band).
    f = feasibility(pool_qty=10, estimated_qualifiers=0, cap=10, x=1)
    assert f["race_intensity"] == 0
    assert f["fit_score"] == 0
    assert f["suggested_cap"] is None  # no cap makes an empty race healthy


def test_feasibility_suggested_cap_hits_target_band():
    """suggested_cap = qualifiers / 3.0 target, clamped >= 1 — applying it must
    land the fit inside the healthy [2, 5] band."""
    for qualifiers in (3, 41, 337, 4743):
        f = feasibility(pool_qty=qualifiers * 2, estimated_qualifiers=qualifiers, cap=999, x=1)
        s = f["suggested_cap"]
        assert s >= 1
        assert 2.0 <= qualifiers / s <= 5.0
    # Tiny fields clamp to cap 1 (3 qualifiers / 1 slot = fit 3.0).
    assert feasibility(pool_qty=6, estimated_qualifiers=3, cap=13, x=1)["suggested_cap"] == 1


def test_feasibility_balanced_ratio_is_defined():
    # The old metric returned None here (log(1)=0); the ratio is a defined 1.0.
    f = feasibility(pool_qty=10, estimated_qualifiers=10, cap=10, x=1)
    assert f["race_intensity"] == 1
    assert f["fit_score"] == 1.0


def test_feasibility_zero_cap():
    f = feasibility(pool_qty=10, estimated_qualifiers=0, cap=0, x=1)
    assert f["race_intensity"] is None
    assert f["fit_score"] is None


# ── rules.build_tier ─────────────────────────────────────────────────────────

def test_build_tier_empty_pool_returns_none_archetype(db):
    result = build_tier("Mythic", [], cap=1, db=db, contract=_CONTRACT)
    assert result["set_rule"]["archetype"] == "none"
    assert result["pool"] == []
    assert result["feasibility"] is None
    assert result["low_feasibility"] is True


def test_build_tier_count_of_pool(db):
    # 10 tokens with Background=Red, spread across 5 wallets holding 2 each.
    for i in range(10):
        owner = f"0xwallet{i // 2}"
        _add_token(db, i + 1, owner)
        _add_trait(db, i + 1, "Background", "Red")
    db.commit()

    tier_traits = [{"rank": 1, "trait_category": "Background", "trait_value": "Red", "combined_score": 1.0}]
    result = build_tier("Common", tier_traits, cap=2, db=db, contract=_CONTRACT)

    assert result["set_rule"]["archetype"] == "count_of_pool"
    assert result["set_rule"]["count_required"] >= 1
    assert result["feasibility"]["pool_qualifying_nfts"] == 10


def test_build_tier_super_rare_count_of_pool(db):
    # Super Rare switched from one_of_each to the inclusive count_of_pool rule
    # (2026-06-30): the fixed-combo rule produced near-empty races. It now builds
    # a pool-count set_rule (pool + count_required), not a fixed trait_values combo.
    _add_token(db, 1, "0xA")
    _add_trait(db, 1, "Background", "Gold")
    _add_token(db, 2, "0xA")
    _add_trait(db, 2, "Eyes", "Laser")
    _add_token(db, 3, "0xB")
    _add_trait(db, 3, "Background", "Gold")
    db.commit()

    tier_traits = [
        {"rank": 1, "trait_category": "Background", "trait_value": "Gold", "combined_score": 1.0},
        {"rank": 2, "trait_category": "Eyes", "trait_value": "Laser", "combined_score": 0.9},
    ]
    result = build_tier("Super Rare", tier_traits, cap=1, db=db, contract=_CONTRACT)

    assert result["set_rule"]["archetype"] == "count_of_pool"
    assert result["set_rule"]["count_required"] >= 1
    assert "pool" in result["set_rule"]
    assert "trait_values" not in result["set_rule"]


def _gold_pool(db, n: int, owner: str = "0xW") -> list[dict]:
    """n tokens all bearing Background=Gold, held by one wallet (so count isn't
    clamped by the pool)."""
    for i in range(n):
        _add_token(db, i + 1, owner)
        _add_trait(db, i + 1, "Background", "Gold")
    db.commit()
    return [{"rank": 1, "trait_category": "Background", "trait_value": "Gold", "combined_score": 1.0}]


def test_build_tier_default_count_escalates_with_rarity(db):
    # Regression: the set size must NOT collapse to 1 for rarer tiers. With a pool
    # big enough to avoid clamping, each tier gets its graduated default.
    traits = _gold_pool(db, 8)
    assert build_tier("Common", traits, cap=2, db=db, contract=_CONTRACT)["set_rule"]["count_required"] == 1
    assert build_tier("Uncommon", traits, cap=2, db=db, contract=_CONTRACT)["set_rule"]["count_required"] == 2
    assert build_tier("Rare", traits, cap=2, db=db, contract=_CONTRACT)["set_rule"]["count_required"] == 2
    assert build_tier("Super Rare", traits, cap=2, db=db, contract=_CONTRACT)["set_rule"]["count_required"] == 3
    mythic = build_tier("Mythic", traits, cap=2, db=db, contract=_CONTRACT)
    assert mythic["set_rule"]["archetype"] == "apex_combo"
    assert mythic["set_rule"]["count_required"] == 3


def test_build_tier_count_required_override(db):
    # An explicit operator set size overrides the tier default.
    traits = _gold_pool(db, 8)
    result = build_tier("Uncommon", traits, cap=2, db=db, contract=_CONTRACT, count_required=5)
    assert result["set_rule"]["count_required"] == 5


def test_build_tier_count_clamped_to_pool(db):
    # A set size larger than the band's pool is clamped down (can't require more
    # tokens than exist in the band).
    traits = _gold_pool(db, 2)
    result = build_tier("Mythic", traits, cap=1, db=db, contract=_CONTRACT, count_required=5)
    assert result["set_rule"]["count_required"] == 2


# ── rules.detect_ladders ──────────────────────────────────────────────────────

def test_detect_ladders_no_overlap_for_disjoint_pools():
    tier_a = {
        "tier": "A",
        "pool": [{"trait_category": "Background", "trait_value": "Red"}],
        "set_rule": {"archetype": "count_of_pool", "count_required": 1},
    }
    tier_b = {
        "tier": "B",
        "pool": [{"trait_category": "Eyes", "trait_value": "Laser"}],
        "set_rule": {"archetype": "count_of_pool", "count_required": 2},
    }
    assert detect_ladders([tier_a, tier_b]) == []


def test_detect_ladders_detects_overlap():
    pool = [{"trait_category": "Background", "trait_value": "Yellow"}]
    tier_a = {"tier": "Common", "pool": pool, "set_rule": {"archetype": "count_of_pool", "count_required": 3}}
    tier_b = {"tier": "Uncommon", "pool": pool, "set_rule": {"archetype": "count_of_pool", "count_required": 6}}

    ladders = detect_ladders([tier_a, tier_b])
    assert len(ladders) == 1
    assert ladders[0]["tier_a"] == "Common"
    assert ladders[0]["tier_b"] == "Uncommon"
    assert ladders[0]["x_a"] == 3
    assert ladders[0]["x_b"] == 6


# ── /atlas API ─────────────────────────────────────────────────────────────────

def _ranking_manifest(n_traits: int, approved: bool) -> dict:
    return {
        "manifest_id": str(uuid.uuid4()),
        "schema_version": "1.0",
        "collection": {
            "contract_address": _CONTRACT, "chain": "eth",
            "total_supply": n_traits, "eligible_supply": n_traits,
        },
        "trait_rankings": [
            {
                "rank": i + 1,
                "trait_category": "Trait",
                "trait_value": f"v{i+1}",
                "combined_score": 1.0 - i * 1e-6,
                "pinned": False,
            }
            for i in range(n_traits)
        ],
        "approval": (
            {"approver_address": "0xabc", "approved_at": "2026-01-01T00:00:00+00:00", "manifest_hash": "0x" + "00" * 32}
            if approved else None
        ),
    }


def _seed_ranking_job(db, tmp_path, n_traits: int, approved: bool) -> dict:
    manifest = _ranking_manifest(n_traits, approved)
    marker = write_ranking_manifest(_CONTRACT, manifest)
    db.add(IngestJob(
        id=str(uuid.uuid4()), contract_address=_CONTRACT, chain="eth",
        status="complete", manifest_path=marker,
    ))
    db.commit()
    return manifest


def _seed_tokens(db, n_traits: int) -> None:
    """Two tokens per trait value, each owned by a distinct wallet."""
    for i in range(n_traits):
        for j in range(2):
            tid = i * 2 + j
            _add_token(db, tid, f"0xwallet{tid}")
            _add_trait(db, tid, "Trait", f"v{i+1}")
    db.commit()


def test_atlas_generate_no_completed_job_returns_404(client):
    r = client.post("/atlas/generate", json={"contract_address": _CONTRACT})
    assert r.status_code == 404


def test_atlas_generate_requires_approval(client, db, tmp_path):
    _seed_ranking_job(db, tmp_path, n_traits=20, approved=False)
    r = client.post("/atlas/generate", json={"contract_address": _CONTRACT})
    assert r.status_code == 400


def test_atlas_preview_404_before_generate(client):
    r = client.get(f"/atlas/preview/{_CONTRACT}")
    assert r.status_code == 404


def test_atlas_generate_and_preview(client, db, tmp_path):
    manifest = _seed_ranking_job(db, tmp_path, n_traits=20, approved=True)
    _seed_tokens(db, 20)

    r = client.post("/atlas/generate", json={"contract_address": _CONTRACT})
    assert r.status_code == 200
    body = r.json()

    assert body["ranking_manifest_id"] == manifest["manifest_id"]
    assert set(body["tier_structure"].keys()) == set(DEFAULT_TIER_STRUCTURE.keys())
    assert [t["tier"] for t in body["tiers"]] == TIER_OUTPUT_ORDER
    assert sum(len(t["pool"]) for t in body["tiers"]) == 20
    assert isinstance(body["ladders"], list)
    assert body["approval"] is None

    preview = client.get(f"/atlas/preview/{_CONTRACT}")
    assert preview.status_code == 200
    assert preview.json()["atlas_manifest_id"] == body["atlas_manifest_id"]

    # Atlas persisted to the DB store (replaces the old OUTPUT_DIR file check).
    stored = load_atlas_manifest(_CONTRACT)
    assert stored is not None
    assert stored["atlas_manifest_id"] == body["atlas_manifest_id"]
