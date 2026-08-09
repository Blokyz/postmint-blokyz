"""Celery tasks for the transfer poller + Claimed-event reconciler.

`poll_transfers` pulls new NFT transfers and updates ownership + acquisition
timestamps (windows are derived from `acquired_at`, so there is no window state
to maintain here). `reconcile_claims` records on-chain wins the DB missed.

Beat schedule lives in app/worker.py (intervals from Settings). Both tasks are
resumable/idempotent, so firing them on any cadence is safe — a longer gap just
means more pages/blocks per cycle. Run beat via scripts/run_celery_beat.ps1.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.claims.reconcile import NoSeason, reconcile_claims
from app.claims.transfers import poll_transfers
from app.collections_registry import list_collections
from app.config import get_settings
from app.db.session import SessionLocal
from app.ttl_cache import contract_keys, race_cache
from app.worker import celery_app

log = logging.getLogger(__name__)

# ~11h on Base's 2s blocks — deep enough that an overnight beat outage can't
# open a gap, shallow enough to stay a handful of chunked eth_getLogs calls.
RECONCILE_LOOKBACK_BLOCKS = 20_000


def poll_all_published(db: Session) -> dict:
    """One beat cycle: poll transfers for every published collection.

    Per-collection commit + try/except so one Moralis failure can't kill the
    whole cycle (the documented failure mode is quota exhaustion)."""
    polled: dict[str, dict] = {}
    failed: dict[str, str] = {}
    for col in list_collections(db):
        try:
            polled[col.contract_address] = poll_transfers(db, col.contract_address, col.chain)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.exception("transfer poll failed for %s", col.contract_address)
            failed[col.contract_address] = str(exc)[:200]
    return {"polled": polled, "failed": failed}


def reconcile_all_seasons(db: Session, lookback_blocks: int = RECONCILE_LOOKBACK_BLOCKS) -> dict:
    """One beat cycle: reconcile on-chain Claimed events for every published
    collection that has a registered season. Auto-recovers wins whose frontend
    confirm never fired (tab close, smart-account phantom hashes)."""
    rpc_url = get_settings().base_sepolia_rpc_url
    reconciled: dict[str, dict] = {}
    failed: dict[str, str] = {}
    for col in list_collections(db):
        contract = col.contract_address
        try:
            out = reconcile_claims(db, contract, rpc_url, lookback_blocks=lookback_blocks)
            db.commit()
            if out["recorded"]:
                race_cache.invalidate(*contract_keys(contract))
            reconciled[contract] = {"recorded": len(out["recorded"]), "skipped": out["skipped"]}
        except NoSeason:
            continue  # no claim contract registered yet — nothing to reconcile
        except Exception as exc:
            db.rollback()
            log.exception("reconcile failed for %s", contract)
            failed[contract] = str(exc)[:200]
    return {"reconciled": reconciled, "failed": failed}


@celery_app.task(name="app.tasks.claims.poll_transfers")
def poll_transfers_task(contract: str, chain: str) -> dict:
    """Poll one contract's transfers and update ownership. Commits on success."""
    db = SessionLocal()
    try:
        summary = poll_transfers(db, contract, chain)
        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="app.tasks.claims.poll_all_transfers")
def poll_all_transfers_task() -> dict:
    """Beat entry: poll every published collection (commits per collection)."""
    db = SessionLocal()
    try:
        return poll_all_published(db)
    finally:
        db.close()


@celery_app.task(name="app.tasks.claims.reconcile_all")
def reconcile_all_task() -> dict:
    """Beat entry: reconcile every published collection with a season."""
    db = SessionLocal()
    try:
        return reconcile_all_seasons(db)
    finally:
        db.close()
