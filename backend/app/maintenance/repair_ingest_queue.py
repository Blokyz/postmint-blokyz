"""Repair orphaned ingest jobs and stale Redis queue state.

Usage (from backend/ with venv active):
    python -m app.maintenance.repair_ingest_queue
    python -m app.maintenance.repair_ingest_queue --requeue
"""

from __future__ import annotations

import argparse
import logging
import sys

from redis import Redis
from sqlalchemy import select, text

from app.config import get_settings
from app.db.models import IngestJob, Token
from app.db.session import SessionLocal
from app.tasks.ingest import run_ingest

log = logging.getLogger(__name__)

ORPHAN_MSG = "orphaned: repaired by repair_ingest_queue (redis/db drift)"
EMPTY_COMPLETE_MSG = "invalid: marked complete with zero tokens in database"


def _redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def stop_duplicate_celery_workers() -> int:
    """Best-effort kill of stray celery.exe processes on Windows (dev only)."""
    if sys.platform != "win32":
        return 0
    stopped = 0
    try:
        import subprocess

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name = 'celery.exe'\" | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            if line.strip().isdigit():
                stopped += 1
    except Exception as exc:
        log.warning("Could not stop duplicate celery workers: %s", exc)
    if stopped:
        log.info("Stopped %d celery.exe process(es)", stopped)
    return stopped


def purge_stale_ingestion_queue(redis: Redis) -> int:
    """Remove leftover messages on the ingestion queue (e.g. after worker crashes)."""
    deleted = 0
    # Celery/Kombu list key for direct queue named "ingestion"
    for key in ("ingestion", "celery"):
        length = redis.llen(key)
        if length:
            redis.delete(key)
            deleted += int(length)
            log.info("Purged %d message(s) from Redis list %r", length, key)
    return deleted


def fail_empty_complete_jobs(db) -> list[str]:
    """Mark complete jobs that have no tokens as failed."""
    rows = db.execute(
        text("""
            SELECT j.id, j.contract_address
            FROM ingest_jobs j
            LEFT JOIN (
                SELECT contract_address, COUNT(*) AS n
                FROM tokens
                GROUP BY contract_address
            ) t ON t.contract_address = j.contract_address
            WHERE j.status = 'complete'
              AND COALESCE(t.n, 0) = 0
        """)
    ).fetchall()

    ids: list[str] = []
    for job_id, _contract in rows:
        job = db.get(IngestJob, job_id)
        if not job:
            continue
        job.status = "failed"
        job.error_message = EMPTY_COMPLETE_MSG
        job.progress_pct = 0
        ids.append(job_id)
    if ids:
        db.commit()
    return ids


def fail_stuck_active_jobs(db) -> list[str]:
    """Mark pending/running jobs failed so a fresh ingest can be queued."""
    jobs = db.scalars(
        select(IngestJob).where(IngestJob.status.in_(["pending", "running"]))
    ).all()
    ids: list[str] = []
    for job in jobs:
        job.status = "failed"
        job.error_message = ORPHAN_MSG
        job.progress_pct = 0
        ids.append(job.id)
    if ids:
        db.commit()
    return ids


def requeue_failed_for_contract(db, contract: str | None) -> list[str]:
    """Re-dispatch Celery tasks for recently failed jobs (optional contract filter)."""
    q = (
        select(IngestJob)
        .where(IngestJob.status == "failed")
        .where(IngestJob.error_message.in_([ORPHAN_MSG, EMPTY_COMPLETE_MSG]))
        .order_by(IngestJob.created_at.desc())
    )
    if contract:
        q = q.where(IngestJob.contract_address == contract.lower())

    jobs = db.scalars(q).all()
    dispatched: list[str] = []
    for job in jobs:
        job.status = "pending"
        job.error_message = None
        job.progress_pct = 0
        job.last_cursor = None
        db.commit()
        run_ingest.delay(job.id)
        dispatched.append(job.id)
        log.info("Re-queued job %s for %s", job.id, job.contract_address)
    return dispatched


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Repair ingest Redis/DB drift")
    parser.add_argument(
        "--requeue",
        action="store_true",
        help="Reset repaired failed jobs to pending and dispatch Celery tasks",
    )
    parser.add_argument(
        "--contract",
        default=None,
        help="Only requeue failed jobs for this contract (with --requeue)",
    )
    parser.add_argument(
        "--skip-redis",
        action="store_true",
        help="Do not purge stale Redis queue lists",
    )
    parser.add_argument(
        "--stop-workers",
        action="store_true",
        help="Stop duplicate celery.exe processes before repair (Windows dev)",
    )
    args = parser.parse_args(argv)

    redis = _redis_client()
    try:
        redis.ping()
        log.info("Redis OK at %s", get_settings().redis_url)
    except Exception as exc:
        log.error("Redis unreachable: %s", exc)
        return 1

    if args.stop_workers:
        stop_duplicate_celery_workers()

    if not args.skip_redis:
        purged = purge_stale_ingestion_queue(redis)
        log.info("Redis purge complete (%d messages removed)", purged)

    db = SessionLocal()
    try:
        empty_complete = fail_empty_complete_jobs(db)
        if empty_complete:
            log.info("Failed %d empty 'complete' job(s): %s", len(empty_complete), empty_complete)

        stuck = fail_stuck_active_jobs(db)
        if stuck:
            log.info("Failed %d stuck pending/running job(s): %s", len(stuck), stuck)

        if not empty_complete and not stuck:
            log.info("No stuck or empty-complete ingest jobs in Postgres")

        if args.requeue:
            dispatched = requeue_failed_for_contract(db, args.contract)
            if dispatched:
                log.info("Dispatched %d job(s) to Celery", len(dispatched))
            else:
                log.info("No repaired jobs to requeue (run without --contract to see all)")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
