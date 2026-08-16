"""Championship standings + driver-card aggregates (Phase 3 collector layer).

Read-only rollups over the `claims` table + the approved atlas manifest that power
two display surfaces:

- ``build_standings`` — a whole-collection board: per-tier grid fill plus a ranking
  of wallets by **championship points** (CP). CP is a *display* metric derived
  purely from on-chain wins (a won claim = points by tier rarity) — NOT an
  off-chain economy, so it never competes with the on-chain "first N per tier" race
  as a source of truth.
- ``build_driver`` — one wallet's per-tier state (won / ready / racing / locked)
  + its CP and win count, for the driver card.

Since the 2026-08-04 design change windows are derived from acquisition history,
so "racers" here means **wallets currently holding a qualifying set** (from the
ownership snapshot), not opted-in clocks — a qualified wallet is racing by
definition (its countdown started at its X-th acquisition).

CP weights are keyed by the default tier names, falling back to a rarity ramp
indexed by the tier's position in the atlas (rarest tiers score highest).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.atlas.pools import wallet_counts_for_pool
from app.claims.acquisitions import ensure_acquired_at, set_completed_at
from app.claims.eligibility import (
    consumed_token_ids,
    evaluate_wallet,
    tier_exclude_pairs,
    tier_pool_pairs,
)
from app.claims.windows import derive_status, tier_window_seconds
from app.db.models import Claim

# Points a single won slot is worth, by tier. Rarer tier => more points.
_CP_BY_TIER = {"Common": 5, "Uncommon": 10, "Rare": 15, "Super Rare": 25, "Mythic": 50}
# Fallback ramp by tier index (position in the atlas `tiers` list, rarest last).
_CP_RAMP = [5, 10, 15, 25, 50]


def championship_points(tier: str, tier_index: int) -> int:
    """CP for one won slot in `tier`. Known tiers use the fixed table; unknown tier
    names fall back to the rarity ramp indexed by manifest position."""
    if tier in _CP_BY_TIER:
        return _CP_BY_TIER[tier]
    return _CP_RAMP[min(max(tier_index, 0), len(_CP_RAMP) - 1)]


def _tier_index_map(manifest: dict) -> dict[str, int]:
    return {t.get("tier"): i for i, t in enumerate(manifest.get("tiers", []))}


def qualified_wallets(db: Session, contract: str, tier_entry: dict) -> dict[str, int]:
    """Wallets currently holding the tier's qualifying set -> their held count.

    One aggregate over the ownership snapshot (`wallet_counts_for_pool`). For the
    defensive `one_of_each` archetype this approximates with count >= K (no
    default tier uses it since 2026-06-30). Tokens consumed by a won claim in
    this tier are excluded, so a wallet whose whole set is spent stops counting
    as a racer until it assembles a fresh one."""
    rule = tier_entry.get("set_rule") or {}
    pool = tier_pool_pairs(tier_entry)
    if rule.get("archetype") == "one_of_each":
        required = len(rule.get("trait_values") or [])
    else:
        required = int(rule.get("count_required") or 0)
    if not pool or required <= 0:
        return {}
    used = consumed_token_ids(db, contract.lower(), tier_entry.get("tier", ""))
    counts = wallet_counts_for_pool(
        db, contract.lower(), pool, exclude_token_ids=used,
        exclude_pool=tier_exclude_pairs(tier_entry),
    )
    return {w: c for w, c in counts.items() if c >= required}


def tier_fill_counts(db: Session, contract: str) -> dict[str, int]:
    """Per-tier won-slot counts in one aggregate query — never loads claim rows."""
    rows = db.execute(
        select(Claim.tier, func.count().label("won"))
        .where(Claim.contract_address == contract.lower())
        .where(Claim.on_chain_tx_hash.is_not(None))
        .group_by(Claim.tier)
    ).all()
    return {tier: won for tier, won in rows}


def build_standings(db: Session, contract: str, manifest: dict) -> dict:
    """Whole-collection standings: per-tier fill + wallets ranked by CP."""
    contract = contract.lower()
    tier_index = _tier_index_map(manifest)
    tier_structure = manifest.get("tier_structure", {})

    fill = tier_fill_counts(db, contract)

    # Per-tier grid fill. "racers" = wallets currently holding the qualifying
    # set (one aggregate per tier, results TTL-cached by the caller).
    tiers_out = []
    for i, t in enumerate(manifest.get("tiers", [])):
        tier = t.get("tier")
        cap = int((tier_structure.get(tier, {}) or {}).get("cap", 0))
        won = fill.get(tier, 0)
        tiers_out.append(
            {
                "tier": tier,
                "rank": i,
                "cap": cap,
                "slots_filled": won,
                "slots_remaining": max(0, cap - won),
                "racers": len(qualified_wallets(db, contract, t)),
                "points": championship_points(tier, i),
            }
        )

    # Collectors: rank wallets by summed CP over their won slots. Grouped in SQL
    # (bounded by wallets x tiers), never one row per claim.
    won_rows = db.execute(
        select(
            Claim.wallet_address,
            Claim.tier,
            func.count().label("wins"),
            func.max(Claim.window_completed).label("latest"),
        )
        .where(Claim.contract_address == contract)
        .where(Claim.on_chain_tx_hash.is_not(None))
        .group_by(Claim.wallet_address, Claim.tier)
    ).all()

    agg: dict[str, dict] = {}
    for wallet, tier, wins, latest in won_rows:
        a = agg.setdefault(
            wallet,
            {"wallet_address": wallet, "tiers_won": [], "championship_points": 0, "latest_at": None},
        )
        a["tiers_won"].extend([tier] * wins)
        a["championship_points"] += wins * championship_points(tier, tier_index.get(tier, 0))
        if latest is not None:
            completed = latest.isoformat()
            if a["latest_at"] is None or completed > a["latest_at"]:
                a["latest_at"] = completed

    collectors = sorted(
        agg.values(),
        key=lambda c: (-c["championship_points"], c["latest_at"] or ""),
    )
    for rank, c in enumerate(collectors, start=1):
        c["rank"] = rank
        c["badges_won"] = len(c["tiers_won"])

    return {"contract_address": contract, "tiers": tiers_out, "collectors": collectors}


def build_driver(
    db: Session, contract: str, wallet: str, manifest: dict, chain: str = "eth"
) -> dict:
    """One wallet's per-tier crest state + CP total, for the driver card.

    States: won / ready / racing / locked (qualification implies racing —
    the derived window is always running). May lazily backfill `acquired_at`
    (no-op after the first call); the caller should commit.
    """
    contract, wallet = contract.lower(), wallet.lower()
    now = datetime.now(timezone.utc)

    win_rows = db.execute(
        select(Claim.tier, Claim.slot_number)
        .where(Claim.contract_address == contract)
        .where(Claim.wallet_address == wallet)
        .where(Claim.on_chain_tx_hash.is_not(None))
    ).all()
    wins_by_tier: dict[str, list[int | None]] = {}
    for tier, slot in win_rows:
        wins_by_tier.setdefault(tier, []).append(slot)

    eligs = {e.tier: e for e in evaluate_wallet(db, contract, wallet, manifest)}

    # One acquisition backfill covers every tier (pools are disjoint) — only
    # needed when some non-instant tier actually qualifies.
    if any(
        e.qualifies and tier_window_seconds(manifest, e.tier) > 0 for e in eligs.values()
    ):
        ensure_acquired_at(db, contract, wallet, chain)

    tiers_out = []
    cp_total = 0
    badges_won = 0
    for i, t in enumerate(manifest.get("tiers", [])):
        tier = t.get("tier")
        elig = eligs.get(tier)
        slots = wins_by_tier.get(tier, [])
        won_count = len(slots)
        badges_won += won_count
        pts = championship_points(tier, i)
        cp_total += won_count * pts

        if won_count > 0:
            state = "won"
        elif elig and elig.qualifies:
            window_seconds = tier_window_seconds(manifest, tier)
            completed = (
                set_completed_at(db, contract, wallet, elig.qualifying_token_ids, elig.count_required)
                if window_seconds > 0
                else None
            )
            state = derive_status(now, completed, window_seconds, qualifies=True, won=False)[
                "status"
            ]
        else:
            state = "locked"

        tiers_out.append(
            {
                "tier": tier,
                "rank": i,
                "state": state,
                "won_count": won_count,
                "slot_numbers": sorted(s for s in slots if s is not None),
                "held_count": elig.held_count if elig else 0,
                "count_required": elig.count_required if elig else 0,
                "progress_pct": elig.progress_pct if elig else 0.0,
                "needed": elig.needed if elig else 0,
                "points": pts,
            }
        )

    return {
        "contract_address": contract,
        "wallet_address": wallet,
        "championship_points": cp_total,
        "badges_won": badges_won,
        "tiers": tiers_out,
    }
