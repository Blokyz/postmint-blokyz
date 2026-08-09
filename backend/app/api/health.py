from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.collections_registry import list_collections
from app.db.models import TransferSync
from app.db.session import get_db

router = APIRouter(tags=["health"])

# A poller older than this is presumed dead (the real failure mode is silent
# death — Moralis quota exhaustion has hit twice). Alert on `any_stale`.
POLLER_STALE_AFTER_SECONDS = 1800


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "postmint-backend",
        "claim_chain": "base-sepolia",
        "chain_id": 84532,
    }


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/health/poller")
def health_poller(db: Session = Depends(get_db)) -> dict:
    """Transfer-poller staleness per published collection. A stale poller means
    ownership data is frozen — people who sold still look qualified."""
    now = datetime.now(timezone.utc)
    collections = []
    for col in list_collections(db):
        sync = db.get(TransferSync, col.contract_address)
        age = (now - sync.updated_at).total_seconds() if sync and sync.updated_at else None
        collections.append(
            {
                "contract_address": col.contract_address,
                "slug": col.slug,
                "last_block": sync.last_block if sync else None,
                "last_poll_at": sync.updated_at.isoformat() if sync and sync.updated_at else None,
                "age_seconds": int(age) if age is not None else None,
                "stale": age is None or age > POLLER_STALE_AFTER_SECONDS,
            }
        )
    return {
        "stale_after_seconds": POLLER_STALE_AFTER_SECONDS,
        "any_stale": any(c["stale"] for c in collections),
        "collections": collections,
    }
