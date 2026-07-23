"""Season registry + claim-nonce allocation (Phase 3 claim API).

A *season* is a deployed `SetClaimManager` contract. It's created on-chain (by the
platform, via `SetClaimFactory.deploySeason`), then recorded here so the backend
can bind a claim attestation to the correct season contract address.
`/claim/sign` resolves the season via `latest_season(contract)` and allocates a
single-use nonce via `allocate_nonce`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ClaimNonce, Season


def record_season(
    db: Session,
    contract: str,
    manager_address: str,
    chain_id: int,
    atlas_hash: str | None = None,
    deployed_at: datetime | None = None,
) -> Season:
    """Register a deployed `SetClaimManager`. Idempotent on `manager_address`:
    re-registering the same manager returns the existing row (refreshing its
    atlas_hash/deployed_at). Flushes; the caller commits."""
    manager_address = manager_address.lower()
    existing = db.scalar(select(Season).where(Season.manager_address == manager_address))
    if existing is not None:
        if atlas_hash is not None:
            existing.atlas_hash = atlas_hash
        if deployed_at is not None:
            existing.deployed_at = deployed_at
        db.flush()
        return existing

    season = Season(
        contract_address=contract.lower(),
        manager_address=manager_address,
        chain_id=chain_id,
        atlas_hash=atlas_hash,
        deployed_at=deployed_at,
    )
    db.add(season)
    db.flush()
    return season


def latest_season(db: Session, contract: str) -> Season | None:
    """The most recently registered season for a contract (highest id), or None."""
    return db.scalar(
        select(Season)
        .where(Season.contract_address == contract.lower())
        .order_by(Season.id.desc())
    )


def allocate_nonce(
    db: Session,
    season: Season,
    tier: str,
    wallet: str,
    expiry: int,
) -> int:
    """Reserve a single-use nonce for one on-chain claim. The row id IS the nonce.
    Flushes so the autoincrement id is assigned; the caller commits."""
    row = ClaimNonce(
        season_id=season.id,
        contract_address=season.contract_address,
        tier=tier,
        wallet_address=wallet.lower(),
        manager_address=season.manager_address,
        expiry=expiry,
    )
    db.add(row)
    db.flush()
    return row.id
