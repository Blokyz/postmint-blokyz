import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ApproveRequest,
    ApproveResponse,
    IngestRequest,
    IngestResponse,
    StatusResponse,
)
from app.config import get_settings
from app.db.models import IngestJob
from app.db.session import get_db
from app.manifests import compute_manifest_hash
from app.tasks.ingest import run_ingest

router = APIRouter(prefix="/audit", tags=["audit"])
settings = get_settings()


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    if not settings.moralis_api_key:
        raise HTTPException(status_code=503, detail="MORALIS_API_KEY is not configured.")

    # Resume if an active job already exists for this contract.
    existing = db.scalar(
        select(IngestJob)
        .where(IngestJob.contract_address == req.contract_address)
        .where(IngestJob.status.notin_(["failed", "complete"]))
        .order_by(IngestJob.created_at.desc())
    )
    if existing:
        # Re-dispatch in case the Celery message was lost (Redis restart, worker crash).
        run_ingest.delay(existing.id)
        return IngestResponse(
            job_id=existing.id,
            contract_address=existing.contract_address,
            status=existing.status,
            message="Active job found — re-queued worker (resumes from last cursor if set).",
        )

    job = IngestJob(
        id=str(uuid.uuid4()),
        contract_address=req.contract_address,
        chain=req.chain,
        status="pending",
    )
    db.add(job)
    db.commit()

    run_ingest.delay(job.id)

    return IngestResponse(
        job_id=job.id,
        contract_address=job.contract_address,
        status="pending",
        message="Ingestion queued.",
    )


@router.get("/status/{contract}", response_model=StatusResponse)
def status(contract: str, db: Session = Depends(get_db)) -> StatusResponse:
    job = db.scalar(
        select(IngestJob)
        .where(IngestJob.contract_address == contract.lower())
        .order_by(IngestJob.created_at.desc())
    )
    return StatusResponse(
        contract_address=contract.lower(),
        job_id=job.id if job else None,
        status=job.status if job else None,
        progress_pct=job.progress_pct if job else None,
        error_message=job.error_message if job else None,
    )


@router.get("/ranking/{contract}")
def ranking(contract: str, db: Session = Depends(get_db)) -> dict:
    job = db.scalar(
        select(IngestJob)
        .where(IngestJob.contract_address == contract.lower())
        .where(IngestJob.status == "complete")
        .order_by(IngestJob.created_at.desc())
    )
    if not job:
        raise HTTPException(
            status_code=404,
            detail="No completed ingestion found for this contract.",
        )
    if not job.manifest_path:
        raise HTTPException(status_code=500, detail="Manifest path missing on completed job.")

    path = Path(job.manifest_path)
    if not path.exists():
        raise HTTPException(status_code=500, detail="Manifest file missing from disk.")

    return json.loads(path.read_text())


@router.post("/approve", response_model=ApproveResponse)
def approve(req: ApproveRequest, db: Session = Depends(get_db)) -> ApproveResponse:
    job = db.scalar(
        select(IngestJob)
        .where(IngestJob.contract_address == req.contract_address)
        .where(IngestJob.status == "complete")
        .order_by(IngestJob.created_at.desc())
    )
    if not job or not job.manifest_path:
        raise HTTPException(
            status_code=404,
            detail="No completed ingestion found for this contract.",
        )

    path = Path(job.manifest_path)
    if not path.exists():
        raise HTTPException(status_code=500, detail="Manifest file missing from disk.")

    manifest = json.loads(path.read_text())
    existing = {(r["trait_category"], r["trait_value"]): r for r in manifest["trait_rankings"]}
    submitted = [(t.trait_category, t.trait_value) for t in req.trait_rankings]

    if len(submitted) != len(set(submitted)):
        raise HTTPException(status_code=400, detail="Submitted trait_rankings contains duplicates.")
    if set(submitted) != set(existing):
        raise HTTPException(
            status_code=400,
            detail="Submitted trait_rankings must contain exactly the traits in the manifest "
            "(no additions, removals, or renames).",
        )

    reordered = []
    for i, t in enumerate(req.trait_rankings):
        row = dict(existing[(t.trait_category, t.trait_value)])
        row["rank"] = i + 1
        row["pinned"] = t.pinned
        reordered.append(row)

    manifest["trait_rankings"] = reordered
    manifest["approval"] = None
    manifest_hash = compute_manifest_hash(manifest)
    approved_at = datetime.now(timezone.utc).isoformat()
    manifest["approval"] = {
        "approver_address": req.approver_address,
        "approved_at": approved_at,
        "manifest_hash": manifest_hash,
    }

    path.write_text(json.dumps(manifest, indent=2))

    return ApproveResponse(
        contract_address=req.contract_address,
        manifest_hash=manifest_hash,
        approved_at=approved_at,
        approver_address=req.approver_address,
        trait_count=len(reordered),
    )
