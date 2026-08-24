"""Rarity band slicing — splits an approved ranking manifest's trait_rankings
into the 5 set-atlas tiers.

Rank 1 = rarest trait (highest combined_score). Tiers are listed here from
rarest to most common. Bands always fall on trait boundaries, so pools stay
plain trait lists downstream.

Cut placement (2026-08-18): bands are cut by accumulated TOKEN share, not
trait count. Under exclusive bands (Option A) a token belongs to its RAREST
trait's band, a min-statistic whose distribution depends on traits-per-token —
fixed trait-percentile cuts gave GVC a 37/37% Common/Uncommon split and BAYC
an inverted pyramid (Rare 39%, Common 10%). Cutting when the band's tokens
reach a target share of supply (TOKEN_CUMULATIVE_PCT) yields the same pyramid
on any collection. Trait-percentile cuts (CUMULATIVE_PCT) remain only as the
fallback when no token data is available.

Mythic is the merged apex grail tier: the former Ultra Rare, Legendary,
Mythic, and Secret bands were each so sparse on real collections (often 1-2
qualifiers) that they produced non-races, so they were collapsed into one
contestable tier.
"""

from __future__ import annotations

import math

# Rarest -> most common.
TIER_ORDER: list[str] = [
    "Mythic",
    "Super Rare",
    "Rare",
    "Uncommon",
    "Common",
]

# Cumulative share of TOKENS (the target pyramid: 1/4/10/25/60% of NFTs).
TOKEN_CUMULATIVE_PCT: dict[str, float] = {
    "Mythic": 0.01,
    "Super Rare": 0.05,
    "Rare": 0.15,
    "Uncommon": 0.40,
    "Common": 1.0,
}

# Cumulative share of TRAITS — fallback cuts when no token data is available.
CUMULATIVE_PCT: dict[str, float] = {
    "Mythic": 0.07,
    "Super Rare": 0.15,
    "Rare": 0.30,
    "Uncommon": 0.50,
    "Common": 1.0,
}


def slice_into_tiers(
    trait_rankings: list[dict],
    marginal_tokens: dict[tuple[str, str], int] | None = None,
) -> dict[str, list[dict]]:
    """Partition trait_rankings (rank 1 = rarest) into the 5 tiers.

    `marginal_tokens` maps (trait_category, trait_value) -> number of tokens
    whose RAREST trait it is under this ordering (pools.rarest_trait_token_counts).
    When provided (and non-zero), bands close when their cumulative token count
    reaches the TOKEN_CUMULATIVE_PCT target; otherwise falls back to
    trait-percentile cuts.

    Returns a dict ordered Mythic -> Common, each value a (possibly empty)
    list of trait_ranking rows whose rank falls in that tier's band.
    Coverage is full and contiguous: every trait belongs to exactly one tier.
    """
    ranked = sorted(trait_rankings, key=lambda r: r["rank"])
    n = len(ranked)

    if marginal_tokens:
        margins = [
            marginal_tokens.get((r["trait_category"], r["trait_value"]), 0) for r in ranked
        ]
        total = sum(margins)
        if total > 0:
            return _slice_by_tokens(ranked, margins, total)

    tiers: dict[str, list[dict]] = {}
    prev_boundary = 0
    for tier in TIER_ORDER:
        boundary = min(n, math.ceil(n * CUMULATIVE_PCT[tier]))
        tiers[tier] = ranked[prev_boundary:boundary]
        prev_boundary = boundary
    return tiers


def _slice_by_tokens(
    ranked: list[dict], margins: list[int], total: int
) -> dict[str, list[dict]]:
    """Cut bands where cumulative token count crosses each tier's target share.

    Nearest-boundary rule: the trait that crosses a target joins the band only
    when overshooting lands closer to the target than stopping short. A band
    always takes at least one trait while traits remain, so a mega-trait can't
    leave Mythic empty (it overshoots instead)."""
    tiers: dict[str, list[dict]] = {}
    i, cum = 0, 0
    for tier in TIER_ORDER:
        target = total * TOKEN_CUMULATIVE_PCT[tier]
        band: list[dict] = []
        while i < len(ranked):
            new = cum + margins[i]
            if band and new > target and (new - target) >= (target - cum):
                break
            band.append(ranked[i])
            cum = new
            i += 1
        tiers[tier] = band
    return tiers
