"""Collections registry API (Phase 1) — slug↔contract tenancy for the holder app.

- ``POST /collections``        — publish/register a collection under a slug (operator).
- ``GET  /collections/{slug}`` — resolve a slug (holder layout; 404 = available).
- ``GET  /collections``        — directory listing with per-collection summary.

NOTE: ``POST /collections`` is currently unauthenticated (platform-operated MVP,
unlisted from the holder side). Gate it before mainnet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import CollectionCreateRequest, CollectionResponse, CollectionSummary
from app.collections_registry import (
    SlugError,
    collection_summary,
    create_collection,
    get_by_slug,
    list_collections,
)
from app.db.session import get_db

router = APIRouter(prefix="/collections", tags=["collections"])


def _to_response(col) -> CollectionResponse:
    return CollectionResponse(
        slug=col.slug,
        contract_address=col.contract_address,
        display_name=col.display_name,
        chain=col.chain,
        image_url=col.image_url,
        published=col.published,
    )


@router.post("", response_model=CollectionResponse)
def publish(req: CollectionCreateRequest, db: Session = Depends(get_db)) -> CollectionResponse:
    """Publish a collection. Slug is validated or derived from `display_name`.
    Idempotent per contract (re-publish keeps the slug)."""
    try:
        col = create_collection(
            db,
            req.contract_address,
            req.display_name,
            slug=req.slug,
            image_url=req.image_url,
            published=req.published,
        )
        db.commit()
    except SlugError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except IntegrityError:
        # Lost a race for the same slug/contract; surface as a conflict.
        db.rollback()
        raise HTTPException(status_code=409, detail="slug or contract already registered")
    return _to_response(col)


@router.get("/{slug}", response_model=CollectionResponse)
def resolve(slug: str, db: Session = Depends(get_db)) -> CollectionResponse:
    """Resolve a slug to its collection. 404 doubles as the availability check."""
    col = get_by_slug(db, slug)
    if col is None:
        raise HTTPException(status_code=404, detail="No collection for this slug.")
    return _to_response(col)


@router.get("", response_model=list[CollectionSummary])
def directory(
    db: Session = Depends(get_db),
    include_unpublished: bool = Query(False, alias="all"),
) -> list[CollectionSummary]:
    """Directory listing (published by default; `?all=true` includes drafts)."""
    return [
        CollectionSummary(**collection_summary(db, col))
        for col in list_collections(db, include_unpublished=include_unpublished)
    ]
