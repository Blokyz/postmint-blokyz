"""Rarity band slicing — splits an approved ranking manifest's trait_rankings
into the 5 set-atlas tiers using cumulative rank-percentage boundaries.

Rank 1 = rarest trait (highest combined_score). Tiers are listed here from
rarest to most common; boundaries are cumulative percentages of N traits.

Mythic is the merged apex grail tier (top 7%): the former Ultra Rare,
Legendary, Mythic, and Secret bands were each so sparse on real collections
(often 1-2 qualifiers) that they produced non-races, so they were collapsed
into one contestable tier.
"""

from __future__ import annotations

import math

# Rarest -> most common, with cumulative rank-% boundaries (PROJECT_MASTER.md §10).
TIER_ORDER: list[str] = [
    "Mythic",
    "Super Rare",
    "Rare",
    "Uncommon",
    "Common",
]

CUMULATIVE_PCT: dict[str, float] = {
    "Mythic": 0.07,
    "Super Rare": 0.15,
    "Rare": 0.30,
    "Uncommon": 0.50,
    "Common": 1.0,
}


def slice_into_tiers(trait_rankings: list[dict]) -> dict[str, list[dict]]:
    """Partition trait_rankings (rank 1 = rarest) into the 5 tiers.

    Returns a dict ordered Mythic -> Common, each value a (possibly empty)
    list of trait_ranking rows whose rank falls in that tier's band.
    Coverage is full and contiguous: every trait belongs to exactly one tier.
    """
    ranked = sorted(trait_rankings, key=lambda r: r["rank"])
    n = len(ranked)

    tiers: dict[str, list[dict]] = {}
    prev_boundary = 0
    for tier in TIER_ORDER:
        boundary = min(n, math.ceil(n * CUMULATIVE_PCT[tier]))
        tiers[tier] = ranked[prev_boundary:boundary]
        prev_boundary = boundary
    return tiers
