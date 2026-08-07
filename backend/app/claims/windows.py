"""Holding-window derivation from on-chain acquisition history.

Model (decided 2026-08-04, replacing the 2026-07-13 explicit-opt-in clock):
- **No opt-in.** A tier's window starts the moment the wallet acquired its X-th
  qualifying token (`acquisitions.set_completed_at` — the X-th-oldest
  `tokens.acquired_at` among the held qualifying set). A long holder is `ready`
  the first time they load the page; a fresh buyer gets an auto-started
  countdown from their real purchase time.
- **No persisted window state.** Status is pure arithmetic over token
  acquisition timestamps — there is nothing to reset; selling below X and
  rebuying restamps `acquired_at` naturally. A `claims` row is only created at
  `/claim/sign` time (so `/claim/confirm` has a row to mark won).
- Window seconds still come from the atlas `tier_structure[tier]
  .holding_window_hours` (kept in lockstep with the deployed season's frozen
  windows): 0 for Common (instant — acquisition data never consulted), a flat
  24 for every other tier by default.

States: `won` | `ready` | `racing` | `not_started` (not qualified). The old
`reset` state is gone with the persisted windows.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.claims.acquisitions import ensure_acquired_at, set_completed_at
from app.claims.eligibility import evaluate_tier, find_tier_entry

STATUS_WON = "won"
STATUS_READY = "ready"
STATUS_RACING = "racing"
STATUS_NOT_STARTED = "not_started"


class UnknownTier(Exception):
    """The requested tier is not present in the atlas manifest."""


# The one flat holding window (2026-08-04): every non-instant tier holds 24h.
# Code-authoritative so a stale pre-change manifest (72-336h values) can never
# enforce an old duration — the manifest only distinguishes instant (0, Common)
# from standard. Seasons must deploy with the same flat windows.
FLAT_WINDOW_SECONDS = 24 * 3600


def tier_window_seconds(atlas_manifest: dict, tier: str) -> int:
    """Required holding-window duration in seconds for `tier`: 0 for instant
    tiers (manifest hours == 0), the flat 24h for everything else."""
    hours = (atlas_manifest.get("tier_structure", {}).get(tier, {}) or {}).get(
        "holding_window_hours", 0
    )
    return 0 if not hours else FLAT_WINDOW_SECONDS


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """Treat naive DB timestamps as UTC (defensive — the column is timezone-aware)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def derive_status(
    now: datetime,
    set_completed: datetime | None,
    window_seconds: int,
    qualifies: bool,
    won: bool,
) -> dict:
    """Pure window-state derivation off the set-completion moment. All the time
    math lives here so it can be unit-tested without a DB.

    `set_completed` is when the wallet acquired its X-th qualifying token; None
    with `qualifies=True` is treated as "completed just now" (unknown history is
    conservative — it can lengthen a wait, never shorten one).
    """
    if won:
        return {"status": STATUS_WON, "seconds_remaining": 0}
    if not qualifies:
        return {"status": STATUS_NOT_STARTED, "seconds_remaining": None}

    set_completed = _aware(set_completed) if set_completed is not None else now
    ready_at = set_completed + timedelta(seconds=window_seconds)

    elapsed = (now - set_completed).total_seconds()
    if elapsed >= window_seconds:
        return {"status": STATUS_READY, "ready_at": ready_at.isoformat(), "seconds_remaining": 0}
    return {
        "status": STATUS_RACING,
        "ready_at": ready_at.isoformat(),
        "seconds_remaining": int(math.ceil(window_seconds - elapsed)),
    }


def window_status(
    db: Session,
    contract: str,
    tier: str,
    wallet: str,
    atlas_manifest: dict,
    chain: str = "eth",
    now: datetime | None = None,
) -> dict:
    """Current derived window status for (contract, tier, wallet).

    For a qualifying wallet on a tier with a non-zero window this lazily
    backfills missing `acquired_at` (one Moralis walk per wallet, ever — see
    acquisitions.ensure_acquired_at), so the caller should COMMIT afterwards to
    persist the stamps. Zero-window tiers (Common) never consult acquisition
    data.
    """
    now = now or _utcnow()
    contract, wallet = contract.lower(), wallet.lower()
    entry = find_tier_entry(atlas_manifest, tier)
    if entry is None:
        raise UnknownTier(tier)

    elig = evaluate_tier(db, contract, wallet, entry)
    window_seconds = tier_window_seconds(atlas_manifest, tier)

    completed: datetime | None = None
    if elig.qualifies and window_seconds > 0:
        # Backfill ALL of the wallet's unstamped tokens in one walk (pools are
        # disjoint across tiers — restricting per-tier would repeat the walk).
        ensure_acquired_at(db, contract, wallet, chain)
        completed = set_completed_at(
            db, contract, wallet, elig.qualifying_token_ids, elig.count_required
        )

    state = derive_status(now, completed, window_seconds, elig.qualifies, won=False)
    return {
        "tier": tier,
        "window_seconds": window_seconds,
        "qualifies": elig.qualifies,
        "held_count": elig.held_count,
        "count_required": elig.count_required,
        "progress_pct": elig.progress_pct,
        "qualifying_token_ids": elig.qualifying_token_ids,
        # The set-completion moment (window start). None for zero-window tiers
        # and non-qualifying wallets. Key name kept from the opt-in era.
        "window_started": _aware(completed).isoformat() if completed is not None else None,
        **state,
    }
