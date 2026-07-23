"""Set-rule archetype generation, feasibility math, and ladder detection."""

from __future__ import annotations

from itertools import combinations

from sqlalchemy.orm import Session

from app.atlas.pools import Pool, pool_token_count, wallet_counts_for_pool, wallet_owners_for_trait

# Tier -> archetype, per PROJECT_MASTER.md §10. Mythic is the merged apex
# grail tier (top 7%): apex_combo is count-of-pool scoped to the rarest band.
# Super Rare was one_of_each until 2026-06-30, but that rule requires holding a
# specific fixed 2-3 trait combo whose tiny owner-intersection produced
# near-empty, non-competitive races (e.g. 2 qualifiers / fit_score 0.21 on real
# collections). Switched to the inclusive count_of_pool rule so the tier draws a
# real field of qualifiers. `_select_one_of_each` below is retained for
# reference/reversibility but is no longer reachable from any default tier.
ARCHETYPE_BY_TIER: dict[str, str] = {
    "Common": "count_of_pool",
    "Uncommon": "count_of_pool",
    "Rare": "count_of_pool",
    "Super Rare": "count_of_pool",
    "Mythic": "apex_combo",
}

# Target band for fit_score (= race_intensity = estimated_qualifiers / cap).
# A "healthy race" is over-subscribed: more qualifiers than cap slots so the
# slots are genuinely contested, but not so many that winning is pure luck.
_FIT_TARGET = 3.0
_FIT_RANGE = (2.0, 5.0)
_ONE_OF_EACH_SEARCH_POOL = 8
_ONE_OF_EACH_MIN_K = 2
_ONE_OF_EACH_MAX_K = 3

# Default set size (count_required) per tier — the number of qualifying tokens a
# wallet must hold from the tier's rarity band. Escalates with rarity so a tier
# is a genuine *set* to assemble, not a trivial "hold one token": rarer tiers
# demand a bigger set. This is a DIRECT product lever (operator-tunable per tier
# via tier_structure[tier]["count_required"]), NOT auto-selected — the old
# fit-based auto-selection collapsed to X=1 on every large pool (any single NFT
# qualified you for Mythic). Competitiveness is tuned separately via `cap`
# (fit_score = estimated_qualifiers / cap).
DEFAULT_COUNT_BY_TIER: dict[str, int] = {
    "Common": 1,
    "Uncommon": 2,
    "Rare": 2,
    "Super Rare": 3,
    "Mythic": 3,
}


def feasibility(pool_qty: int, estimated_qualifiers: int, cap: int, x: int) -> dict:
    """PROJECT_MASTER.md §10 feasibility math.

    fit_score is the over-subscription ratio (estimated_qualifiers / cap): how
    many qualifiers compete per available cap slot. >1 is a real race (more
    qualifiers than slots), <1 is under-subscribed (every qualifier wins, no
    race). It is monotonic in over-subscription and defined at ratio == 1 — the
    previous 1/|log(ratio)| was undefined exactly at the balanced point and
    scored under- and over-subscription symmetrically, so an under-subscribed
    dud scored as "healthy." fit_score equals race_intensity by construction;
    both fields are retained for schema/UI stability. It is None only when cap
    is 0 (no slots configured).
    """
    max_sets_formable = pool_qty // x if x > 0 else None
    race_intensity = estimated_qualifiers / cap if cap > 0 else None
    fit_score = race_intensity  # healthy band applied by callers via _FIT_RANGE

    return {
        "pool_qualifying_nfts": pool_qty,
        "estimated_qualifiers": estimated_qualifiers,
        "max_sets_formable": max_sets_formable,
        "race_intensity": round(race_intensity, 6) if race_intensity is not None else None,
        "fit_score": round(fit_score, 6) if fit_score is not None else None,
    }


def _select_count(
    db: Session, contract: str, pool: Pool, cap: int, count_required: int
) -> tuple[int, dict, bool]:
    """Feasibility for a fixed, operator-chosen set size (count_of_pool /
    apex_combo). `count_required` is a direct lever, not auto-searched. It is
    clamped to [1, pool_qty] so a tier can never demand more tokens than the band
    contains. `low_feasibility` is True when the resulting fit_score falls outside
    the healthy band — a signal to tune `cap` (or the count), not an auto-fix.
    """
    pool_qty = pool_token_count(db, contract, pool)
    x = max(1, min(count_required, pool_qty)) if pool_qty else max(1, count_required)
    if pool_qty == 0:
        return x, feasibility(0, 0, cap, x), True

    counts = wallet_counts_for_pool(db, contract, pool).values()
    estimated_qualifiers = sum(1 for c in counts if c >= x)
    feas = feasibility(pool_qty, estimated_qualifiers, cap, x)
    fit = feas["fit_score"]
    low = fit is None or not (_FIT_RANGE[0] <= fit <= _FIT_RANGE[1])
    return x, feas, low


def _select_one_of_each(db: Session, contract: str, pool: Pool, cap: int) -> tuple[Pool, dict, bool]:
    """Search combinations of the rarest trait values in `pool` for a
    one_of_each trait_values set whose fit_score is closest to target,
    preferring sets within _FIT_RANGE."""
    search_pool = pool[: min(len(pool), _ONE_OF_EACH_SEARCH_POOL)]
    pool_qty = pool_token_count(db, contract, pool)
    owner_sets = [wallet_owners_for_trait(db, contract, c, v) for c, v in search_pool]

    min_k = min(_ONE_OF_EACH_MIN_K, len(search_pool))
    max_k = min(_ONE_OF_EACH_MAX_K, len(search_pool))

    candidates = []
    for k in range(min_k, max_k + 1):
        for combo in combinations(range(len(search_pool)), k):
            intersection = owner_sets[combo[0]]
            for i in combo[1:]:
                intersection = intersection & owner_sets[i]
                if not intersection:
                    break
            trait_values = [search_pool[i] for i in combo]
            candidates.append((trait_values, feasibility(pool_qty, len(intersection), cap, k)))

    in_range = [
        (tv, f) for tv, f in candidates
        if f["fit_score"] is not None and _FIT_RANGE[0] <= f["fit_score"] <= _FIT_RANGE[1]
    ]
    scored = in_range or [(tv, f) for tv, f in candidates if f["fit_score"] is not None]

    if scored:
        trait_values, feas = min(scored, key=lambda c: abs(c[1]["fit_score"] - _FIT_TARGET))
        return trait_values, feas, not in_range

    trait_values, feas = max(candidates, key=lambda c: c[1]["estimated_qualifiers"])
    return trait_values, feas, True


def _pairs_to_dicts(pairs: Pool) -> list[dict]:
    return [{"trait_category": c, "trait_value": v} for c, v in pairs]


def build_tier(
    tier: str,
    tier_traits: list[dict],
    cap: int,
    db: Session,
    contract: str,
    count_required: int | None = None,
) -> dict:
    """Build the {tier, set_rule, pool, feasibility, low_feasibility} entry for one
    tier. `count_required` (the set size) defaults to the graduated
    DEFAULT_COUNT_BY_TIER ramp when not supplied by the caller/operator."""
    pool: Pool = [(t["trait_category"], t["trait_value"]) for t in tier_traits]
    archetype = ARCHETYPE_BY_TIER[tier]
    if count_required is None:
        count_required = DEFAULT_COUNT_BY_TIER.get(tier, 1)

    if not pool:
        return {
            "tier": tier,
            "set_rule": {"archetype": "none"},
            "pool": [],
            "feasibility": None,
            "low_feasibility": True,
        }

    if archetype == "one_of_each":
        trait_values, feas, low = _select_one_of_each(db, contract, pool, cap)
        set_rule = {"archetype": archetype, "trait_values": _pairs_to_dicts(trait_values)}
    else:
        resolved_count, feas, low = _select_count(db, contract, pool, cap, count_required)
        set_rule = {
            "archetype": archetype,
            "pool": _pairs_to_dicts(pool),
            "count_required": resolved_count,
        }

    return {
        "tier": tier,
        "set_rule": set_rule,
        "pool": _pairs_to_dicts(pool),
        "feasibility": feas,
        "low_feasibility": low,
    }


def _rule_x(set_rule: dict) -> int | None:
    archetype = set_rule.get("archetype")
    if archetype in ("count_of_pool", "apex_combo"):
        return set_rule.get("count_required")
    if archetype == "one_of_each":
        return len(set_rule.get("trait_values", []))
    return None


def detect_ladders(tiers: list[dict]) -> list[dict]:
    """Detect adjacent tiers whose pools overlap >70% but require different X.

    Operates on tiers in the order given (adjacent = consecutive list items).
    """
    ladders = []
    for a, b in zip(tiers, tiers[1:]):
        pool_a = {(p["trait_category"], p["trait_value"]) for p in a["pool"]}
        pool_b = {(p["trait_category"], p["trait_value"]) for p in b["pool"]}
        if not pool_a or not pool_b:
            continue

        union = pool_a | pool_b
        intersection = pool_a & pool_b
        overlap = len(intersection) / len(union)

        x_a, x_b = _rule_x(a["set_rule"]), _rule_x(b["set_rule"])
        if overlap > 0.7 and x_a != x_b:
            ladders.append({
                "tier_a": a["tier"],
                "tier_b": b["tier"],
                "shared_pool_size": len(intersection),
                "x_a": x_a,
                "x_b": x_b,
            })
    return ladders
