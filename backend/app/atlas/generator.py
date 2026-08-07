"""Set Atlas generator — orchestrates band slicing, rule generation, and
ladder detection into a manifest matching schemas/set_manifest.schema.json."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.atlas.bands import TIER_ORDER, slice_into_tiers
from app.atlas.rules import DEFAULT_COUNT_BY_TIER, build_tier, detect_ladders

# Default tier structure (cap, holding_window_hours, count_required) —
# project-configurable per season, these are starting defaults. `count_required`
# (the set size) escalates with rarity via DEFAULT_COUNT_BY_TIER so rarer tiers
# demand a bigger assembled set. Mythic is the merged apex grail tier (top 7%).
# Windows are FLAT since 2026-08-04: holding is derived from on-chain acquisition
# history (not an opt-in clock), so every non-Common tier holds 24h and Common is
# instant — per-tier window tuning is retired as a lever (cap is the lever).
DEFAULT_TIER_STRUCTURE: dict[str, dict] = {
    "Common": {"cap": 1000, "holding_window_hours": 0, "count_required": DEFAULT_COUNT_BY_TIER["Common"]},
    "Uncommon": {"cap": 750, "holding_window_hours": 24, "count_required": DEFAULT_COUNT_BY_TIER["Uncommon"]},
    "Rare": {"cap": 500, "holding_window_hours": 24, "count_required": DEFAULT_COUNT_BY_TIER["Rare"]},
    "Super Rare": {"cap": 250, "holding_window_hours": 24, "count_required": DEFAULT_COUNT_BY_TIER["Super Rare"]},
    "Mythic": {"cap": 50, "holding_window_hours": 24, "count_required": DEFAULT_COUNT_BY_TIER["Mythic"]},
}

# Output order: easiest -> hardest (Common -> Secret).
TIER_OUTPUT_ORDER = list(reversed(TIER_ORDER))


def generate_atlas_manifest(
    db: Session,
    contract_address: str,
    ranking_manifest: dict,
    tier_structure: dict[str, dict] | None = None,
) -> dict:
    """Build the atlas manifest dict for `contract_address` from an approved
    `ranking_manifest`. `tier_structure` defaults to `DEFAULT_TIER_STRUCTURE`
    when not provided (or for tiers omitted from a partial override)."""
    # Per-tier deep merge so a partial override (e.g. just cap) keeps the other
    # default fields (count_required, holding_window_hours) instead of dropping them.
    overrides = tier_structure or {}
    tier_structure = {
        tier: {**defaults, **overrides.get(tier, {})}
        for tier, defaults in DEFAULT_TIER_STRUCTURE.items()
    }
    bands = slice_into_tiers(ranking_manifest["trait_rankings"])

    tiers = []
    for tier in TIER_OUTPUT_ORDER:
        cfg = tier_structure[tier]
        tiers.append(
            build_tier(
                tier, bands[tier], cfg["cap"], db, contract_address,
                count_required=cfg.get("count_required"),
            )
        )

    ladders = detect_ladders(tiers)

    return {
        "atlas_manifest_id": str(uuid.uuid4()),
        "ranking_manifest_id": ranking_manifest["manifest_id"],
        "collection": dict(ranking_manifest["collection"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tier_structure": tier_structure,
        "tiers": tiers,
        "ladders": ladders,
        "approval": None,
    }
