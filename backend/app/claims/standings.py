"""Championship standings + driver-card aggregates (Phase 3 collector layer).

Read-only rollups over the `claims` table + the approved atlas manifest that power
two display surfaces:

- ``build_standings`` — a whole-collection board: per-tier grid fill plus a ranking
  of wallets by **championship points** (CP). CP is a *display* metric derived
  purely from on-chain wins (a won claim = points by tier rarity) — NOT an
  off-chain economy, so it never competes with the on-chain "first N per tier" race
  as a source of truth.
- ``build_driver`` — one wallet's per-tier state (won / ready / racing / qualified /
  locked) + its CP and win count, for the driver card.

CP weights are keyed by the default tier names, falling back to a rarity ramp
indexed by the tier's position in the atlas (rarest tiers score highest).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.eligibility import evaluate_wallet
from app.claims.windows import tier_window_seconds, window_status
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


def _is_won(row: Claim) -> bool:
    return row.on_chain_tx_hash is not None


def build_standings(db: Session, contract: str, manifest: dict) -> dict:
    """Whole-collection standings: per-tier fill + wallets ranked by CP."""
    contract = contract.lower()
    tier_index = _tier_index_map(manifest)
    tier_structure = manifest.get("tier_structure", {})

    rows = db.scalars(select(Claim).where(Claim.contract_address == contract)).all()

    # Per-tier grid fill.
    tiers_out = []
    for i, t in enumerate(manifest.get("tiers", [])):
        tier = t.get("tier")
        cap = int((tier_structure.get(tier, {}) or {}).get("cap", 0))
        tier_rows = [r for r in rows if r.tier == tier]
        won = [r for r in tier_rows if _is_won(r)]
        racing = [r for r in tier_rows if not _is_won(r) and r.window_started is not None]
        tiers_out.append(
            {
                "tier": tier,
                "rank": i,
                "cap": cap,
                "slots_filled": len(won),
                "slots_remaining": max(0, cap - len(won)),
                "racers": len(racing),
                "points": championship_points(tier, i),
            }
        )

    # Collectors: rank wallets by summed CP over their won slots.
    agg: dict[str, dict] = {}
    for r in rows:
        if not _is_won(r):
            continue
        a = agg.setdefault(
            r.wallet_address,
            {"wallet_address": r.wallet_address, "tiers_won": [], "championship_points": 0, "latest_at": None},
        )
        a["tiers_won"].append(r.tier)
        a["championship_points"] += championship_points(r.tier, tier_index.get(r.tier, 0))
        if r.window_completed is not None:
            completed = r.window_completed.isoformat()
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


def build_driver(db: Session, contract: str, wallet: str, manifest: dict) -> dict:
    """One wallet's per-tier crest state + CP total, for the driver card."""
    contract, wallet = contract.lower(), wallet.lower()
    tier_index = _tier_index_map(manifest)
    now = datetime.now(timezone.utc)

    won_rows = db.scalars(
        select(Claim)
        .where(Claim.contract_address == contract)
        .where(Claim.wallet_address == wallet)
        .where(Claim.on_chain_tx_hash.is_not(None))
    ).all()
    wins_by_tier: dict[str, list[Claim]] = {}
    for r in won_rows:
        wins_by_tier.setdefault(r.tier, []).append(r)

    eligs = {e.tier: e for e in evaluate_wallet(db, contract, wallet, manifest)}

    tiers_out = []
    cp_total = 0
    badges_won = 0
    for i, t in enumerate(manifest.get("tiers", [])):
        tier = t.get("tier")
        elig = eligs.get(tier)
        wins = wins_by_tier.get(tier, [])
        won_count = len(wins)
        badges_won += won_count
        pts = championship_points(tier, i)
        cp_total += won_count * pts

        if won_count > 0:
            state = "won"
        else:
            ws = window_status(db, contract, tier, wallet, manifest, now=now)
            status = ws["status"]
            if status in ("racing", "ready", "reset"):
                state = status
            elif elig and elig.qualifies:
                state = "qualified"
            else:
                state = "locked"

        slots = sorted(r.slot_number for r in wins if r.slot_number is not None)
        tiers_out.append(
            {
                "tier": tier,
                "rank": i,
                "state": state,
                "won_count": won_count,
                "slot_numbers": slots,
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
