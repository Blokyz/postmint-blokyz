import logging
import os
import sys
from socket import gethostname

from celery import Celery, signals

from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

# Unique nodename avoids DuplicateNodenameWarning when an old worker is still running.
_node_suffix = f"{gethostname()}-{os.getpid()}"
celery_app = Celery(
    "postmint",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.ingest", "app.tasks.claims"],
)

_worker_pool = "solo" if sys.platform == "win32" else "prefork"

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_default_queue="ingestion",
    task_routes={"app.tasks.ingest.run_ingest": {"queue": "ingestion"}},
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=3600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_pool=_worker_pool,
    worker_concurrency=1 if _worker_pool == "solo" else None,
    worker_hostname=f"ingest@{_node_suffix}",
)

# Beat schedule — only fires when a beat process runs (scripts/run_celery_beat.ps1).
# Both tasks are resumable/idempotent, so any cadence is safe.
_beat_schedule = {}
if settings.transfer_poll_interval_seconds > 0:
    _beat_schedule["poll-published-transfers"] = {
        "task": "app.tasks.claims.poll_all_transfers",
        "schedule": float(settings.transfer_poll_interval_seconds),
    }
if settings.reconcile_interval_seconds > 0:
    _beat_schedule["reconcile-claimed-events"] = {
        "task": "app.tasks.claims.reconcile_all",
        "schedule": float(settings.reconcile_interval_seconds),
    }
celery_app.conf.beat_schedule = _beat_schedule


def _mark_job_failed(job_id: str, message: str) -> None:
    from app.db.models import IngestJob
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        job = db.get(IngestJob, job_id)
        if job and job.status in ("pending", "running"):
            job.status = "failed"
            job.error_message = message[:500]
            db.commit()
            log.info("Marked ingest job %s failed: %s", job_id, message[:120])
    except Exception:
        log.exception("Could not mark ingest job %s failed", job_id)
    finally:
        db.close()


@signals.task_failure.connect
def _on_task_failure(sender=None, task_id=None, exception=None, args=None, **kwargs) -> None:
    if sender is None or sender.name != "app.tasks.ingest.run_ingest":
        return
    job_id = args[0] if args else None
    if job_id:
        _mark_job_failed(job_id, str(exception) or "Celery task failed")


@signals.task_revoked.connect
def _on_task_revoked(request=None, terminated=False, signum=None, expired=False, **kwargs) -> None:
    if request is None or request.name != "app.tasks.ingest.run_ingest":
        return
    job_id = request.args[0] if request.args else None
    if job_id:
        _mark_job_failed(job_id, "Celery task revoked")


@signals.worker_ready.connect
def _on_worker_ready(sender=None, **kwargs) -> None:
    log.info(
        "Celery worker ready — pool=%s broker=%s queues=%s",
        celery_app.conf.worker_pool,
        settings.redis_url,
        list(getattr(sender, "queues", []) or ["ingestion"]),
    )
