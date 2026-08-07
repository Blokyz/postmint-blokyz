"""Phase 3 claim/race API.

Off-chain half of the race, exposed over HTTP (PROJECT_MASTER §11):

- ``GET  /eligibility/{contract}/{wallet}``   — per-tier qualification snapshot
- ``GET  /leaderboard/{contract}/{tier}``     — winners + qualified racers in a tier
- ``GET  /claim/status/{contract}/{tier}/{wallet}`` — one wallet's derived window state
- ``POST /claim/sign``                        — backend attestation for `claim()`
- ``POST /claim/confirm``                     — record a landed on-chain claim tx
- ``GET  /winners/{contract}``                — export won slots per tier
- ``POST /claims/season``                     — register a deployed SetClaimManager

Holding windows are DERIVED from on-chain acquisition history (2026-08-04): there
is no opt-in/submit step — a wallet's window for a tier runs from the moment it
acquired its X-th qualifying token. The season contract address a claim binds to
is resolved from the ``seasons`` table (``/claims/season`` registers one). Wins
are recorded when the frontend reports the tx via ``/claim/confirm``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import (
    ClaimConfirmRequest,
    ClaimSignRequest,
    ClaimSignResponse,
    ClaimSyncRequest,
    SeasonRegisterRequest,
    SeasonResponse,
)
from app.api.auth import require_operator_token
from app.claim_signing import backend_signer_address, sign_claim_attestation
from app.claims.acquisitions import oldest_qualifying_set
from app.claims.eligibility import evaluate_wallet, find_tier_entry, shopping_guidance_for_wallet
from app.claims.onchain import ClaimVerificationError, ReceiptNotFound, verify_claim_tx
from app.claims.reconcile import NoSeason, reconcile_claims
from app.claims.seasons import allocate_nonce, latest_season, record_season
from app.claims.standings import build_driver, build_standings, qualified_wallets
from app.claims.windows import (
    UnknownTier,
    tier_window_seconds,
    window_status,
)
from app.config import get_settings
from app.db.models import Claim, Collection
from app.db.session import get_db
from app.manifests import load_atlas_manifest
from app.ttl_cache import contract_keys, race_cache

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


def _active_claim(db: Session, contract: str, tier: str, wallet: str, for_update: bool = False) -> Claim | None:
    stmt = (
        select(Claim)
        .where(Claim.contract_address == contract.lower())
        .where(Claim.tier == tier)
        .where(Claim.wallet_address == wallet.lower())
        .where(Claim.on_chain_tx_hash.is_(None))
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.scalar(stmt)


def _collection_chain(db: Session, contract: str) -> str:
    """Source chain for Moralis lookups (acquisition backfill, shopping links)."""
    col = db.scalar(select(Collection).where(Collection.contract_address == contract.lower()))
    return col.chain if col else "eth"


# --- Read: eligibility + leaderboard ---


@router.get("/eligibility/{contract}/{wallet}")
def eligibility(contract: str, wallet: str, db: Session = Depends(get_db)) -> dict:
    """Per-tier qualification snapshot for a wallet (does not touch windows)."""
    manifest = _require_manifest(contract)
    tiers = [e.to_dict() for e in evaluate_wallet(db, contract, wallet, manifest)]
    return {"contract_address": contract.lower(), "wallet_address": wallet.lower(), "tiers": tiers}


@router.get("/eligibility/{contract}/{wallet}/shopping")
def shopping_guidance(contract: str, wallet: str, db: Session = Depends(get_db)) -> dict:
    """Shopping guidance for short tiers: returns missing count, commoner-first pool traits,
    unowned candidate token IDs, and cross-tier impact."""
    manifest = _require_manifest(contract)
    return shopping_guidance_for_wallet(
        db, contract, wallet, manifest, chain=_collection_chain(db, contract)
    )



@router.get("/standings/{contract}")
def standings(
    contract: str,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    """Whole-collection championship standings: per-tier fill + wallets ranked by CP.
    TTL-cached (polled by every open standings page); claim mutations invalidate.
    Collectors are paginated (`limit`/`offset` over the CP-ranked list)."""
    key = ("standings", contract.lower())
    out = race_cache.get(key, settings.standings_cache_ttl_seconds)
    if out is None:
        manifest = _require_manifest(contract)
        out = build_standings(db, contract, manifest)
        race_cache.set(key, out)
    collectors = out["collectors"]
    return {
        **out,
        "collectors": collectors[offset : offset + limit],
        "total_collectors": len(collectors),
    }


@router.get("/driver/{contract}/{wallet}")
def driver(contract: str, wallet: str, db: Session = Depends(get_db)) -> dict:
    """One wallet's per-tier crest state + championship points (driver card)."""
    manifest = _require_manifest(contract)
    out = build_driver(db, contract, wallet, manifest, chain=_collection_chain(db, contract))
    db.commit()  # persist any lazy acquired_at backfill
    return out


@router.get("/leaderboard/{contract}/{tier}")
def leaderboard(
    contract: str,
    tier: str,
    db: Session = Depends(get_db),
    racers_limit: int = Query(100, ge=1, le=500),
    racers_offset: int = Query(0, ge=0),
) -> dict:
    """Winners (won slots) and racers in a tier. Racers = wallets currently
    holding the qualifying set (windows are derived, so every qualified wallet
    is racing by definition). Per-wallet ready/racing is NOT computed here —
    that would need each racer's acquisition history; `/claim/status` answers it
    for one wallet. Winners are bounded by the tier cap; racers page in-memory
    over the qualified aggregate."""
    manifest = _require_manifest(contract)
    entry = find_tier_entry(manifest, tier)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Tier {tier!r} not in atlas manifest.")

    window_seconds = tier_window_seconds(manifest, tier)
    cap = int((manifest.get("tier_structure", {}).get(tier, {}) or {}).get("cap", 0))

    winner_rows = db.scalars(
        select(Claim)
        .where(Claim.contract_address == contract.lower())
        .where(Claim.tier == tier)
        .where(Claim.on_chain_tx_hash.is_not(None))
    ).all()

    winners = [
        {
            "wallet_address": r.wallet_address,
            "slot_number": r.slot_number,
            "tokens": r.qualifying_tokens or [],
            "tx_hash": r.on_chain_tx_hash,
            "won_at": r.window_completed.isoformat() if r.window_completed else None,
        }
        for r in winner_rows
    ]
    winners.sort(key=lambda w: (w["slot_number"] is None, w["slot_number"]))

    qualified = qualified_wallets(db, contract, entry)
    ranked = sorted(qualified.items(), key=lambda t: (-t[1], t[0]))
    racers = [
        {"wallet_address": w, "held_count": c, "status": "qualified"}
        for w, c in ranked[racers_offset : racers_offset + racers_limit]
    ]

    return {
        "contract_address": contract.lower(),
        "tier": tier,
        "cap": cap,
        "window_seconds": window_seconds,
        "slots_filled": len(winners),
        "slots_remaining": max(0, cap - len(winners)),
        "winners": winners,
        "racers": racers,
        "total_racers": len(qualified),
    }


# --- Window status (derived from acquisition history — no opt-in/submit) ---


@router.get("/claim/status/{contract}/{tier}/{wallet}")
def claim_status(contract: str, tier: str, wallet: str, db: Session = Depends(get_db)) -> dict:
    """Derived holding-window status for one wallet+tier. May lazily backfill
    the wallet's acquisition timestamps (one Moralis walk per wallet, ever)."""
    manifest = _require_manifest(contract)
    try:
        out = window_status(
            db, contract, tier, wallet, manifest, chain=_collection_chain(db, contract)
        )
    except UnknownTier:
        raise HTTPException(status_code=404, detail=f"Tier {tier!r} not in atlas manifest.")
    db.commit()  # persist any lazy acquired_at backfill
    return out


# --- Claim attestation + confirmation ---


@router.post("/claim/sign", response_model=ClaimSignResponse)
def claim_sign(req: ClaimSignRequest, db: Session = Depends(get_db)) -> ClaimSignResponse:
    """Backend-sign a claim tuple so the wallet can submit `SetClaimManager.claim`.
    Only issued when the derived window is `ready` (the wallet completed its set
    >= the holding window ago; instant for zero-window tiers). The attestation
    binds `msg.sender == wallet`, so only that wallet can use it.

    The signed `windowStartedAt` is the set-completion moment from acquisition
    history. The status derivation runs inside this transaction against current
    ownership, so the attestation always reflects the holdings at signing time
    (the on-chain ownership check is the final arbiter regardless)."""
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
        status = window_status(
            db,
            req.contract_address,
            req.tier,
            req.wallet_address,
            manifest,
            chain=_collection_chain(db, req.contract_address),
        )
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

    # Bind EXACTLY one set — the count_required oldest-held qualifying tokens
    # (the ones whose acquisition completed the set, matching the derived
    # window start). Never the whole holding: only these tokens are consumed on
    # the win, so a whale holding 6 on a 2-set tier keeps racing with the
    # other 4.
    token_ids = oldest_qualifying_set(
        db,
        req.contract_address,
        req.wallet_address,
        list(status["qualifying_token_ids"]),
        int(status["count_required"]),
    )
    if not token_ids:
        # Holdings changed between derivation and selection (same-tx re-read).
        raise HTTPException(
            status_code=409,
            detail={"error": "not_ready", "status": "not_started", "seconds_remaining": None},
        )
    if status["window_started"] is not None:
        started_dt = datetime.fromisoformat(status["window_started"])
    else:
        # Zero-window tier (Common): any past timestamp satisfies the contract's
        # elapsed check. Back-date a minute so backend/chain clock skew can't
        # make `block.timestamp >= windowStartedAt` fail.
        started_dt = _utcnow() - timedelta(seconds=60)

    # Record/refresh the claim row now so /claim/confirm has a row to mark won
    # (there is no submit step anymore). The one-active-window unique index makes
    # a concurrent first-sign race an IntegrityError -> retryable 409.
    row = _active_claim(db, req.contract_address, req.tier, req.wallet_address, for_update=True)
    if row is None:
        row = Claim(
            contract_address=req.contract_address.lower(),
            tier=req.tier,
            wallet_address=req.wallet_address.lower(),
        )
        db.add(row)
    row.window_started = started_dt
    row.qualifying_tokens = token_ids
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "concurrent_sign", "retryable": True, "message": "Retry shortly."},
        )

    window_started_at = _unix(started_dt)
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

    The tx is verified on-chain first (a genuine ``Claimed`` event on the season
    manager for this wallet+tier) — the DB is the prize source of truth, so a
    client-supplied hash is never trusted blindly. The authoritative slot number
    is read from the event. Once won the wallet may start a fresh window for
    another slot (the no-whale-cap rule)."""
    row = _active_claim(db, req.contract_address, req.tier, req.wallet_address)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No active claim window to confirm for this wallet+tier.",
        )

    season = latest_season(db, req.contract_address)
    if season is None:
        raise HTTPException(
            status_code=404,
            detail="No season (SetClaimManager) registered for this contract.",
        )

    try:
        result = verify_claim_tx(
            settings.base_sepolia_rpc_url,
            req.tx_hash,
            season.manager_address,
            req.wallet_address,
            req.tier,
        )
    except ReceiptNotFound:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "tx_not_found",
                "retryable": True,
                "message": "Claim tx not yet visible on-chain — retry shortly.",
            },
        )
    except ClaimVerificationError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_claim_tx", "message": str(exc)})
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail="Could not reach the chain RPC to verify the claim tx — retry shortly.",
        )

    row.on_chain_tx_hash = req.tx_hash
    row.window_completed = _utcnow()
    row.slot_number = result["slot_number"]  # authoritative on-chain slot
    try:
        db.commit()
    except IntegrityError:
        # slot_number collides with an already-recorded winner in this tier.
        db.rollback()
        raise HTTPException(status_code=409, detail="slot_number already recorded for this tier.")

    race_cache.invalidate(*contract_keys(req.contract_address))
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


# One chain scan per contract per this many seconds, however many holders poll.
_SYNC_THROTTLE_SECONDS = 10
# Small window: /claim/sync recovers a claim submitted minutes ago, not history
# (~2h on Base's 2s blocks). The operator reconcile endpoint covers deep scans.
_SYNC_LOOKBACK_BLOCKS = 4_000


@router.post("/claim/sync")
def claim_sync(req: ClaimSyncRequest, db: Session = Depends(get_db)) -> dict:
    """Holder-facing claim recovery. Smart-account wallets (e.g. MetaMask
    delegation) wrap the claim tx, so the frontend's receipt-watcher waits on a
    hash that never mines while the real wrapped tx succeeds. This scans the
    season manager's recent ``Claimed`` logs (throttled to one scan per
    contract per 10s — concurrent pollers just read the DB) and reports whether
    the wallet's win is now recorded. Safe to expose: it only records
    chain-verified, backend-signed events."""
    contract = req.contract_address.lower()
    throttle_key = ("claim-sync", contract)
    if race_cache.get(throttle_key, _SYNC_THROTTLE_SECONDS) is None:
        race_cache.set(throttle_key, True)
        try:
            out = reconcile_claims(
                db, contract, settings.base_sepolia_rpc_url, lookback_blocks=_SYNC_LOOKBACK_BLOCKS
            )
            db.commit()
            if out["recorded"]:
                race_cache.invalidate(*contract_keys(contract))
        except NoSeason:
            raise HTTPException(
                status_code=404, detail="No season (SetClaimManager) registered for this contract."
            )
        except (ClaimVerificationError, httpx.HTTPError):
            db.rollback()  # chain unreachable — degrade to answering from the DB

    row = db.scalar(
        select(Claim)
        .where(Claim.contract_address == contract)
        .where(Claim.tier == req.tier)
        .where(Claim.wallet_address == req.wallet_address.lower())
        .where(Claim.on_chain_tx_hash.is_not(None))
        .order_by(Claim.id.desc())
    )
    return {
        "won": row is not None,
        "tier": req.tier,
        "wallet_address": req.wallet_address.lower(),
        "slot_number": row.slot_number if row else None,
        "tx_hash": row.on_chain_tx_hash if row else None,
    }


@router.post("/claims/reconcile/{contract}")
def reconcile(
    contract: str,
    db: Session = Depends(get_db),
    lookback_blocks: int = Query(200_000, ge=1, le=2_000_000),
    _auth: None = Depends(require_operator_token),
) -> dict:
    """Scan the season manager's on-chain ``Claimed`` logs and record any wins
    the DB is missing (frontend confirm can be broken by tab-closes or MetaMask
    Smart Account tx-wrapping — the chain is the source of truth). Idempotent;
    gated by the operator bearer token when configured (open in dev)."""
    try:
        out = reconcile_claims(
            db, contract, settings.base_sepolia_rpc_url, lookback_blocks=lookback_blocks
        )
    except NoSeason:
        raise HTTPException(
            status_code=404, detail="No season (SetClaimManager) registered for this contract."
        )
    except ClaimVerificationError as exc:
        raise HTTPException(status_code=503, detail=f"Chain RPC rejected the scan: {exc}")
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not reach the chain RPC — retry shortly.")
    db.commit()
    if out["recorded"]:
        race_cache.invalidate(*contract_keys(contract))
    return out


# --- Season registry ---


@router.post("/claims/season", response_model=SeasonResponse)
def register_season(
    req: SeasonRegisterRequest,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_operator_token),
) -> SeasonResponse:
    """Register a deployed `SetClaimManager` so `/claim/sign` can attest for it.
    Idempotent on `manager_address`. Platform-operated: gated by the operator
    bearer token when `operator_api_token` is configured (open in dev)."""
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
