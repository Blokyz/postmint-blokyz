"""Celery task for the transfer poller.

Runs `poll_transfers` for a contract: pulls new NFT transfers and updates
ownership + acquisition timestamps (windows are derived from `acquired_at`, so
there is no window state to maintain here).

NOTE: Celery beat is NOT configured in this project (see app/worker.py), so this
task is not auto-scheduled. Drive it by an external scheduler, a beat schedule, or
an interval trigger. It resumes from the `transfer_sync` high-water block, so
firing it on any cadence is safe — a longer gap just means more pages per cycle.
"""

from __future__ import annotations

from app.claims.transfers import poll_transfers
from app.db.session import SessionLocal
from app.worker import celery_app


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
