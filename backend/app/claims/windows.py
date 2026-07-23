"""Holding-window state machine (PROJECT_MASTER §11), backed by the `claims` table.

Model (decisions taken 2026-07-13):
- **Explicit opt-in**: a window starts only when the holder calls `/claim/submit`
  (via `submit_window`) and is found to qualify — the engine does not auto-track
  windows for every qualifying wallet.
- **Reset when count drops below X**: an active window resets only if the wallet's
  qualifying-token count falls below the tier's `count_required` (a holder who
  swaps one qualifying token for another, still holding >= X, keeps their window).

A `claims` row is the window record. State is derived from its columns:
- `window_started` NULL                        -> not_started (opted in, cleared/reset)
- `window_started` set, `on_chain_tx_hash` NULL, still qualifies, elapsed < window   -> racing
- ... elapsed >= window                          -> ready (eligible for a claim sig)
- ... no longer qualifies                        -> reset (poller will clear window_started)
- `on_chain_tx_hash` set                         -> won

Windows are frozen per season; the required duration is read from the atlas
manifest's `tier_structure[tier].holding_window_hours`.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.eligibility import TierEligibility, evaluate_tier, find_tier_entry
from app.db.models import Claim

STATUS_WON = "won"
STATUS_READY = "ready"
STATUS_RACING = "racing"
STATUS_RESET = "reset"
STATUS_NOT_STARTED = "not_started"


class UnknownTier(Exception):
    """The requested tier is not present in the atlas manifest."""


class NotQualified(Exception):
    """The wallet does not currently hold the qualifying set for the tier."""

    def __init__(self, eligibility: TierEligibility):
        self.eligibility = eligibility
        super().__init__(
            f"wallet holds {eligibility.held_count}/{eligibility.count_required} "
            f"for tier {eligibility.tier!r} (needs {eligibility.needed} more)"
        )


def tier_window_seconds(atlas_manifest: dict, tier: str) -> int:
    """Required holding-window duration in seconds for `tier`."""
    hours = (atlas_manifest.get("tier_structure", {}).get(tier, {}) or {}).get(
        "holding_window_hours", 0
    )
    return int(hours) * 3600


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """Treat naive DB timestamps as UTC (defensive — the column is timezone-aware)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def derive_status(
    now: datetime,
    window_started: datetime | None,
    window_seconds: int,
    qualifies: bool,
    won: bool,
) -> dict:
    """Pure window-state derivation. All the time math lives here so it can be
    unit-tested without a DB."""
    if won:
        return {"status": STATUS_WON, "seconds_remaining": 0}
    if window_started is None:
        return {"status": STATUS_NOT_STARTED, "seconds_remaining": None}

    window_started = _aware(window_started)
    ready_at = window_started + timedelta(seconds=window_seconds)

    if not qualifies:
        return {
            "status": STATUS_RESET,
            "ready_at": ready_at.isoformat(),
            "seconds_remaining": None,
        }

    elapsed = (now - window_started).total_seconds()
    if elapsed >= window_seconds:
        return {"status": STATUS_READY, "ready_at": ready_at.isoformat(), "seconds_remaining": 0}
    return {
        "status": STATUS_RACING,
        "ready_at": ready_at.isoformat(),
        "seconds_remaining": int(math.ceil(window_seconds - elapsed)),
    }


def _active_row(db: Session, contract: str, tier: str, wallet: str) -> Claim | None:
    """The single un-won window row for (contract, tier, wallet), if any."""
    return db.scalar(
        select(Claim)
        .where(Claim.contract_address == contract.lower())
        .where(Claim.tier == tier)
        .where(Claim.wallet_address == wallet.lower())
        .where(Claim.on_chain_tx_hash.is_(None))
    )


def _status_payload(
    tier: str, elig: TierEligibility, row: Claim | None, window_seconds: int, now: datetime
) -> dict:
    won = row is not None and row.on_chain_tx_hash is not None
    started = row.window_started if row is not None else None
    state = derive_status(now, started, window_seconds, elig.qualifies, won)
    return {
        "tier": tier,
        "window_seconds": window_seconds,
        "qualifies": elig.qualifies,
        "held_count": elig.held_count,
        "count_required": elig.count_required,
        "progress_pct": elig.progress_pct,
        "qualifying_token_ids": elig.qualifying_token_ids,
        "window_started": _aware(started).isoformat() if started is not None else None,
        **state,
    }


def submit_window(
    db: Session,
    contract: str,
    tier: str,
    wallet: str,
    atlas_manifest: dict,
    now: datetime | None = None,
) -> dict:
    """Start (or resume) a holding window for a qualifying wallet. Idempotent: an
    already-running window is returned unchanged (the clock is NOT restarted).

    Raises `UnknownTier` if the tier isn't in the manifest, `NotQualified` if the
    wallet doesn't currently hold the set. Flushes; the caller commits.
    """
    now = now or _utcnow()
    contract, wallet = contract.lower(), wallet.lower()
    entry = find_tier_entry(atlas_manifest, tier)
    if entry is None:
        raise UnknownTier(tier)

    elig = evaluate_tier(db, contract, wallet, entry)
    if not elig.qualifies:
        raise NotQualified(elig)

    row = _active_row(db, contract, tier, wallet)
    if row is None:
        row = Claim(contract_address=contract, tier=tier, wallet_address=wallet)
        db.add(row)

    # Start the clock only for a fresh/reset window — don't restart a running one.
    if row.window_started is None:
        row.window_started = now
        row.qualifying_tokens = elig.qualifying_token_ids
        row.window_completed = None

    db.flush()
    return _status_payload(tier, elig, row, tier_window_seconds(atlas_manifest, tier), now)


def window_status(
    db: Session,
    contract: str,
    tier: str,
    wallet: str,
    atlas_manifest: dict,
    now: datetime | None = None,
) -> dict:
    """Current window status for (contract, tier, wallet) — no mutation."""
    now = now or _utcnow()
    entry = find_tier_entry(atlas_manifest, tier)
    if entry is None:
        raise UnknownTier(tier)
    elig = evaluate_tier(db, contract, wallet, entry)
    row = _active_row(db, contract, tier, wallet)
    return _status_payload(tier, elig, row, tier_window_seconds(atlas_manifest, tier), now)


def reset_window(row: Claim) -> None:
    """Clear a window (transfer-out dropped the wallet below X). Keeps the row (the
    wallet's opt-in) so a re-submit reuses it."""
    row.window_started = None
    row.qualifying_tokens = None
    row.window_completed = None


def reset_if_unqualified(
    db: Session, contract: str, wallet: str, atlas_manifest: dict
) -> list[str]:
    """Re-evaluate every active window for `wallet` and reset any that no longer
    qualify. Returns the list of tiers that were reset. Used by the transfer poller
    after ownership updates. Flushes; caller commits.
    """
    contract, wallet = contract.lower(), wallet.lower()
    rows = db.scalars(
        select(Claim)
        .where(Claim.contract_address == contract)
        .where(Claim.wallet_address == wallet)
        .where(Claim.on_chain_tx_hash.is_(None))
        .where(Claim.window_started.is_not(None))
    ).all()

    reset_tiers: list[str] = []
    for row in rows:
        entry = find_tier_entry(atlas_manifest, row.tier)
        if entry is None:
            continue
        elig = evaluate_tier(db, contract, wallet, entry)
        if not elig.qualifies:
            reset_window(row)
            reset_tiers.append(row.tier)
    if reset_tiers:
        db.flush()
    return reset_tiers
