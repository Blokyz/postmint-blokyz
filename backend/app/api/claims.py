"""Phase 3 claim/race API.

Off-chain half of the race, exposed over HTTP (PROJECT_MASTER §11):

- ``GET  /eligibility/{contract}/{wallet}``   — per-tier qualification snapshot
- ``GET  /leaderboard/{contract}/{tier}``     — winners + racers in a tier
- ``POST /claim/submit``                      — opt in / start a holding window
- ``GET  /claim/status/{contract}/{tier}/{wallet}`` — one wallet's window state
- ``POST /claim/sign``                        — backend attestation for `claim()`
- ``POST /claim/confirm``                     — record a landed on-chain claim tx
- ``GET  /winners/{contract}``                — export won slots per tier
- ``POST /claims/season``                     — register a deployed SetClaimManager

The season contract address a claim binds to is resolved from the ``seasons``
table (``/claims/season`` registers one). Wins are recorded when the frontend
reports the tx via ``/claim/confirm``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import (
    ClaimConfirmRequest,
    ClaimSignRequest,
    ClaimSignResponse,
    ClaimSubmitRequest,
    SeasonRegisterRequest,
    SeasonResponse,
)
from app.claim_signing import backend_signer_address, sign_claim_attestation
from app.claims.eligibility import evaluate_wallet, find_tier_entry
from app.claims.seasons import allocate_nonce, latest_season, record_season
from app.claims.standings import build_driver, build_standings
from app.claims.windows import (
    NotQualified,
    UnknownTier,
    derive_status,
    submit_window,
    tier_window_seconds,
    window_status,
)
from app.config import get_settings
from app.db.models import Claim
from app.db.session import get_db
from app.manifests import load_atlas_manifest

router = APIRouter(tags=["claims"])
settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_manifest(contract: str) -> dict:
    manifest = load_atlas_manifest(contract)
    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail="No atlas manifest for this contract — generate one first.",
        )
    return manifest


def _unix(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _active_claim(db: Session, contract: str, tier: str, wallet: str) -> Claim | None:
    return db.scalar(
        select(Claim)
        .where(Claim.contract_address == contract.lower())
        .where(Claim.tier == tier)
        .where(Claim.wallet_address == wallet.lower())
        .where(Claim.on_chain_tx_hash.is_(None))
    )


# --- Read: eligibility + leaderboard ---


@router.get("/eligibility/{contract}/{wallet}")
def eligibility(contract: str, wallet: str, db: Session = Depends(get_db)) -> dict:
    """Per-tier qualification snapshot for a wallet (does not touch windows)."""
    manifest = _require_manifest(contract)
    tiers = [e.to_dict() for e in evaluate_wallet(db, contract, wallet, manifest)]
    return {"contract_address": contract.lower(), "wallet_address": wallet.lower(), "tiers": tiers}


@router.get("/standings/{contract}")
def standings(contract: str, db: Session = Depends(get_db)) -> dict:
    """Whole-collection championship standings: per-tier fill + wallets ranked by CP."""
    manifest = _require_manifest(contract)
    return build_standings(db, contract, manifest)


@router.get("/driver/{contract}/{wallet}")
def driver(contract: str, wallet: str, db: Session = Depends(get_db)) -> dict:
    """One wallet's per-tier crest state + championship points (driver card)."""
    manifest = _require_manifest(contract)
    return build_driver(db, contract, wallet, manifest)


@router.get("/leaderboard/{contract}/{tier}")
def leaderboard(contract: str, tier: str, db: Session = Depends(get_db)) -> dict:
    """Winners (won slots) and racers (active windows) in a tier."""
    manifest = _require_manifest(contract)
    if find_tier_entry(manifest, tier) is None:
        raise HTTPException(status_code=404, detail=f"Tier {tier!r} not in atlas manifest.")

    window_seconds = tier_window_seconds(manifest, tier)
    cap = int((manifest.get("tier_structure", {}).get(tier, {}) or {}).get("cap", 0))
    now = _utcnow()

    rows = db.scalars(
        select(Claim)
        .where(Claim.contract_address == contract.lower())
        .where(Claim.tier == tier)
    ).all()

    winners, racers = [], []
    for r in rows:
        if r.on_chain_tx_hash is not None:
            winners.append(
                {
                    "wallet_address": r.wallet_address,
                    "slot_number": r.slot_number,
                    "tokens": r.qualifying_tokens or [],
                    "tx_hash": r.on_chain_tx_hash,
                    "won_at": r.window_completed.isoformat() if r.window_completed else None,
                }
            )
        elif r.window_started is not None:
            # Optimistic time-based state; the transfer poller resets any racer that
            # has since fallen below the qualifying count.
            state = derive_status(now, r.window_started, window_seconds, qualifies=True, won=False)
            racers.append(
                {
                    "wallet_address": r.wallet_address,
                    "window_started": _unix(r.window_started),
                    "status": state["status"],
                    "seconds_remaining": state.get("seconds_remaining"),
                }
            )

    winners.sort(key=lambda w: (w["slot_number"] is None, w["slot_number"]))
    racers.sort(key=lambda x: x["window_started"])
    return {
        "contract_address": contract.lower(),
        "tier": tier,
        "cap": cap,
        "window_seconds": window_seconds,
        "slots_filled": len(winners),
        "slots_remaining": max(0, cap - len(winners)),
        "winners": winners,
        "racers": racers,
    }


# --- Windows: submit + status ---


@router.post("/claim/submit")
def claim_submit(req: ClaimSubmitRequest, db: Session = Depends(get_db)) -> dict:
    """Opt in to (start or resume) a holding window. Requires the wallet to
    currently hold the qualifying set."""
    manifest = _require_manifest(req.contract_address)
    try:
        out = submit_window(db, req.contract_address, req.tier, req.wallet_address, manifest)
        db.commit()
        return out
    except UnknownTier:
        db.rollback()
        raise HTTPException(status_code=404, detail=f"Tier {req.tier!r} not in atlas manifest.")
    except NotQualified as exc:
        db.rollback()
        e = exc.eligibility
        raise HTTPException(
            status_code=409,
            detail={
                "error": "not_qualified",
                "held_count": e.held_count,
                "count_required": e.count_required,
                "needed": e.needed,
            },
        )
    except IntegrityError:
        # A concurrent submit won the one-active-window index; return the live state.
        db.rollback()
        return window_status(db, req.contract_address, req.tier, req.wallet_address, manifest)


@router.get("/claim/status/{contract}/{tier}/{wallet}")
def claim_status(contract: str, tier: str, wallet: str, db: Session = Depends(get_db)) -> dict:
    """Current holding-window status for one wallet+tier (no mutation)."""
    manifest = _require_manifest(contract)
    try:
        return window_status(db, contract, tier, wallet, manifest)
    except UnknownTier:
        raise HTTPException(status_code=404, detail=f"Tier {tier!r} not in atlas manifest.")


# --- Claim attestation + confirmation ---


@router.post("/claim/sign", response_model=ClaimSignResponse)
def claim_sign(req: ClaimSignRequest, db: Session = Depends(get_db)) -> ClaimSignResponse:
    """Backend-sign a claim tuple so the wallet can submit `SetClaimManager.claim`.
    Only issued when the window is `ready` (elapsed + still qualifying). The
    attestation binds `msg.sender == wallet`, so only that wallet can use it."""
    if not settings.backend_signer_private_key:
        raise HTTPException(status_code=503, detail="BACKEND_SIGNER_PRIVATE_KEY is not configured.")

    manifest = _require_manifest(req.contract_address)
    season = latest_season(db, req.contract_address)
    if season is None:
        raise HTTPException(
            status_code=404,
            detail="No season (SetClaimManager) registered for this contract.",
        )

    try:
        status = window_status(db, req.contract_address, req.tier, req.wallet_address, manifest)
    except UnknownTier:
        raise HTTPException(status_code=404, detail=f"Tier {req.tier!r} not in atlas manifest.")

    if status["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "not_ready",
                "status": status["status"],
                "seconds_remaining": status.get("seconds_remaining"),
            },
        )

    row = _active_claim(db, req.contract_address, req.tier, req.wallet_address)
    if row is None or row.window_started is None:
        # Should not happen when status == ready, but guard defensively.
        raise HTTPException(status_code=409, detail={"error": "no_active_window"})

    token_ids = list(status["qualifying_token_ids"])
    window_started_at = _unix(row.window_started)
    expiry = _unix(_utcnow()) + settings.claim_sig_ttl_seconds
    nonce = allocate_nonce(db, season, req.tier, req.wallet_address, expiry)

    signature = sign_claim_attestation(
        settings.backend_signer_private_key,
        season.chain_id,
        season.manager_address,
        req.contract_address,
        req.wallet_address,
        req.tier,
        token_ids,
        window_started_at,
        expiry,
        nonce,
    )
    db.commit()

    return ClaimSignResponse(
        contract_address=req.contract_address,
        tier=req.tier,
        wallet_address=req.wallet_address,
        manager_address=season.manager_address,
        chain_id=season.chain_id,
        token_ids=token_ids,
        window_started_at=window_started_at,
        expiry=expiry,
        nonce=nonce,
        signature=signature,
        backend_signer=backend_signer_address(settings.backend_signer_private_key),
    )


@router.post("/claim/confirm")
def claim_confirm(req: ClaimConfirmRequest, db: Session = Depends(get_db)) -> dict:
    """Record a landed on-chain claim tx: marks the wallet's active window as won.
    Once won (on_chain_tx_hash set) the wallet may start a fresh window for another
    slot (the no-whale-cap rule)."""
    row = _active_claim(db, req.contract_address, req.tier, req.wallet_address)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No active claim window to confirm for this wallet+tier.",
        )

    row.on_chain_tx_hash = req.tx_hash
    row.window_completed = _utcnow()
    if req.slot_number is not None:
        row.slot_number = req.slot_number
    try:
        db.commit()
    except IntegrityError:
        # slot_number collides with an already-recorded winner in this tier.
        db.rollback()
        raise HTTPException(status_code=409, detail="slot_number already recorded for this tier.")

    return {
        "status": "won",
        "contract_address": req.contract_address,
        "tier": req.tier,
        "wallet_address": req.wallet_address,
        "tx_hash": req.tx_hash,
        "slot_number": row.slot_number,
    }


@router.get("/winners/{contract}")
def winners(contract: str, db: Session = Depends(get_db)) -> dict:
    """Export all won slots for a contract, grouped by tier."""
    rows = db.scalars(
        select(Claim)
        .where(Claim.contract_address == contract.lower())
        .where(Claim.on_chain_tx_hash.is_not(None))
        .order_by(Claim.tier, Claim.slot_number)
    ).all()

    by_tier: dict[str, list[dict]] = {}
    for r in rows:
        by_tier.setdefault(r.tier, []).append(
            {
                "wallet_address": r.wallet_address,
                "slot_number": r.slot_number,
                "tokens": r.qualifying_tokens or [],
                "tx_hash": r.on_chain_tx_hash,
                "won_at": r.window_completed.isoformat() if r.window_completed else None,
            }
        )

    return {"contract_address": contract.lower(), "total": len(rows), "winners_by_tier": by_tier}


# --- Season registry ---


@router.post("/claims/season", response_model=SeasonResponse)
def register_season(req: SeasonRegisterRequest, db: Session = Depends(get_db)) -> SeasonResponse:
    """Register a deployed `SetClaimManager` so `/claim/sign` can attest for it.
    Idempotent on `manager_address`. (Platform-operated; deploy script calls this.)"""
    season = record_season(
        db,
        req.contract_address,
        req.manager_address,
        settings.chain_id,
        atlas_hash=req.atlas_hash,
    )
    db.commit()
    return SeasonResponse(
        contract_address=season.contract_address,
        manager_address=season.manager_address,
        atlas_hash=season.atlas_hash,
        chain_id=season.chain_id,
    )
