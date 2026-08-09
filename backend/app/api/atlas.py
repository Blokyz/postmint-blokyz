from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    AtlasGenerateRequest,
    LockAttestationRequest,
    LockAttestationResponse,
)
from app.attestation import backend_signer_address, sign_lock_attestation
from app.atlas.generator import generate_atlas_manifest
from app.config import get_settings
from app.db.models import IngestJob
from app.db.session import get_db
from app.manifests import (
    compute_manifest_hash,
    load_atlas_manifest,
    load_ranking_manifest,
    write_atlas_manifest,
)

router = APIRouter(prefix="/atlas", tags=["atlas"])
settings = get_settings()


@router.post("/generate")
def generate(req: AtlasGenerateRequest, db: Session = Depends(get_db)) -> dict:
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

    ranking_manifest = load_ranking_manifest(req.contract_address)
    if ranking_manifest is None:
        raise HTTPException(status_code=500, detail="Ranking manifest missing from store.")
    if ranking_manifest.get("approval") is None:
        raise HTTPException(
            status_code=400,
            detail="Ranking manifest must be approved before generating an atlas.",
        )

    tier_structure = (
        # exclude_none so an omitted count_required doesn't clobber the graduated
        # default during the per-tier merge in generate_atlas_manifest.
        {tier: override.model_dump(exclude_none=True) for tier, override in req.tier_structure.items()}
        if req.tier_structure
        else None
    )
    atlas_manifest = generate_atlas_manifest(db, req.contract_address, ranking_manifest, tier_structure)
    write_atlas_manifest(req.contract_address, atlas_manifest)
    return atlas_manifest


@router.get("/preview/{contract}")
def preview(contract: str) -> dict:
    manifest = load_atlas_manifest(contract)
    if manifest is None:
        raise HTTPException(status_code=404, detail="No atlas manifest found for this contract.")
    return manifest


@router.post("/lock-attestation", response_model=LockAttestationResponse)
def lock_attestation(req: LockAttestationRequest, db: Session = Depends(get_db)) -> LockAttestationResponse:
    """Backend-sign the ranking+atlas lock tuple so the project owner can call
    `ManifestRegistry.lockManifest`. Requires an *approved* ranking manifest and a
    generated atlas manifest; only then does the backend vouch for the lock.
    """
    if not settings.backend_signer_private_key:
        raise HTTPException(status_code=503, detail="BACKEND_SIGNER_PRIVATE_KEY is not configured.")
    if not settings.manifest_registry_address:
        raise HTTPException(status_code=503, detail="MANIFEST_REGISTRY_ADDRESS is not configured.")

    # Ranking manifest must exist and be approved; reuse the approved manifest_hash
    # so the locked ranking hash is exactly what was signed off-chain.
    job = db.scalar(
        select(IngestJob)
        .where(IngestJob.contract_address == req.contract_address)
        .where(IngestJob.status == "complete")
        .order_by(IngestJob.created_at.desc())
    )
    if not job or not job.manifest_path:
        raise HTTPException(status_code=404, detail="No completed ingestion found for this contract.")
    ranking_manifest = load_ranking_manifest(req.contract_address)
    if ranking_manifest is None:
        raise HTTPException(status_code=500, detail="Ranking manifest missing from store.")
    approval = ranking_manifest.get("approval")
    if approval is None:
        raise HTTPException(
            status_code=400,
            detail="Ranking manifest must be approved before locking.",
        )
    ranking_hash = approval["manifest_hash"]

    # Atlas manifest must have been generated.
    atlas_manifest = load_atlas_manifest(req.contract_address)
    if atlas_manifest is None:
        raise HTTPException(
            status_code=400,
            detail="Atlas manifest must be generated before locking.",
        )
    atlas_hash = compute_manifest_hash(atlas_manifest)

    signature = sign_lock_attestation(
        settings.backend_signer_private_key,
        settings.chain_id,
        settings.manifest_registry_address,
        req.contract_address,
        ranking_hash,
        atlas_hash,
    )

    return LockAttestationResponse(
        contract_address=req.contract_address,
        ranking_hash=ranking_hash,
        atlas_hash=atlas_hash,
        signature=signature,
        backend_signer=backend_signer_address(settings.backend_signer_private_key),
        registry_address=settings.manifest_registry_address.lower(),
        chain_id=settings.chain_id,
    )
