"""Celery task for the holding-window transfer poller.

Runs `poll_transfers` for a contract's live season: pulls new NFT transfers,
updates ownership, and resets windows that fell below the qualifying count.

NOTE: Celery beat is NOT configured in this project (see app/worker.py), so this
task is not auto-scheduled. Drive it by an external scheduler, a beat schedule, or
an interval trigger. It resumes from the `transfer_sync` high-water block, so
firing it on any cadence is safe — a longer gap just means more pages per cycle.
"""

from __future__ import annotations

from app.claims.transfers import poll_transfers
from app.db.session import SessionLocal
from app.manifests import load_atlas_manifest
from app.worker import celery_app


def _load_atlas_manifest(contract: str) -> dict:
    manifest = load_atlas_manifest(contract)
    if manifest is None:
        raise FileNotFoundError(f"No atlas manifest for {contract} — generate one before polling.")
    return manifest


@celery_app.task(name="app.tasks.claims.poll_transfers")
def poll_transfers_task(contract: str, chain: str) -> dict:
    """Poll one contract's transfers and update windows. Commits on success."""
    atlas_manifest = _load_atlas_manifest(contract)
    db = SessionLocal()
    try:
        summary = poll_transfers(db, contract, chain, atlas_manifest)
        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
