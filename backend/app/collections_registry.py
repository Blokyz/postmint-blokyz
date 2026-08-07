"""Collections registry — slug↔contract tenancy for the holder app (Phase 1).

A `Collection` maps a URL-safe slug to a contract so the public app can route by
`/c/{slug}`. Created at the operator's "Publish" step. This module owns the slug
rules (slugify + validation + reserved words) and the read rollups that power the
holder-side collections directory.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.claims.standings import qualified_wallets, tier_fill_counts
from app.config import get_settings
from app.db.models import Collection, IngestJob
from app.manifests import load_atlas_manifest
from app.ttl_cache import race_cache

# Slugs live under /c/, but still keep them clear of app-reserved words so a slug
# can never shadow a real route even if the prefix is dropped later.
RESERVED_SLUGS = {
    "c", "studio", "paddock", "api", "admin", "app", "race", "standings", "driver",
    "collections", "collection", "health", "audit", "atlas", "claim", "claims",
    "winners", "eligibility", "leaderboard", "season", "seasons", "_next",
    "static", "favicon.ico", "robots.txt", "sitemap.xml",
}

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG_MIN, SLUG_MAX = 3, 40


class SlugError(ValueError):
    """Raised when a slug is malformed, reserved, or too short/long."""


def slugify(name: str) -> str:
    """Deterministic slug from a display name: ASCII-fold → lowercase → non-alnum to
    hyphens → collapse/trim → cap at SLUG_MAX. May return '' for name with no
    alphanumerics (caller must handle)."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    lowered = folded.lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    trimmed = re.sub(r"-+", "-", hyphenated).strip("-")
    return trimmed[:SLUG_MAX].strip("-")


def validate_slug(slug: str) -> str:
    """Return the slug if valid, else raise SlugError."""
    if not (SLUG_MIN <= len(slug) <= SLUG_MAX):
        raise SlugError(f"slug must be {SLUG_MIN}-{SLUG_MAX} characters")
    if not _SLUG_RE.match(slug):
        raise SlugError("slug must be lowercase alphanumerics separated by single hyphens")
    if slug in RESERVED_SLUGS:
        raise SlugError(f"slug {slug!r} is reserved")
    return slug


def get_by_slug(db: Session, slug: str) -> Collection | None:
    return db.get(Collection, slug.lower())


def get_by_contract(db: Session, contract: str) -> Collection | None:
    return db.scalar(select(Collection).where(Collection.contract_address == contract.lower()))


def _chain_for(db: Session, contract: str) -> str:
    """Best-effort source chain from the collection's most recent ingest job."""
    job = db.scalar(
        select(IngestJob)
        .where(IngestJob.contract_address == contract.lower())
        .order_by(IngestJob.created_at.desc())
    )
    return job.chain if job else "eth"


def create_collection(
    db: Session,
    contract: str,
    display_name: str,
    slug: str | None = None,
    image_url: str | None = None,
    published: bool = True,
) -> Collection:
    """Publish a collection. Slug is validated (or derived from `display_name`).
    Idempotent per contract: re-publishing an existing contract updates its
    display_name/image/published but KEEPS its slug (changing a slug would break
    shared links). Raises SlugError on a bad/reserved slug or a slug taken by a
    *different* contract. Flushes; caller commits."""
    contract = contract.lower()
    display_name = display_name.strip()
    if not display_name:
        raise SlugError("display_name is required")

    existing = get_by_contract(db, contract)

    resolved = validate_slug((slug or "").strip().lower()) if slug else None
    if resolved is None and existing is None:
        derived = slugify(display_name)
        if not derived:
            raise SlugError("could not derive a slug from display_name — provide one explicitly")
        resolved = validate_slug(derived)

    if existing is not None:
        # Re-publish: keep the slug, refresh the rest.
        existing.display_name = display_name
        if image_url is not None:
            existing.image_url = image_url
        existing.published = published
        db.flush()
        return existing

    clash = get_by_slug(db, resolved)
    if clash is not None:
        raise SlugError(f"slug {resolved!r} is already taken")

    col = Collection(
        slug=resolved,
        contract_address=contract,
        display_name=display_name,
        chain=_chain_for(db, contract),
        image_url=image_url,
        published=published,
    )
    db.add(col)
    db.flush()
    return col


def _status(total_cap: int, total_filled: int) -> str:
    if total_cap <= 0:
        return "pending"
    remaining = total_cap - total_filled
    if remaining <= 0:
        return "full"
    if remaining <= total_cap * 0.1:
        return "ending_soon"
    return "live"


def _claims_rollup(db: Session, contract: str) -> dict:
    """Tier count + slot totals + racing count from the atlas manifest and one
    aggregate claims query. TTL-cached — the directory calls this once per
    collection per request, so uncached it is O(collections x claims)."""
    key = ("summary", contract)
    cached = race_cache.get(key, get_settings().standings_cache_ttl_seconds)
    if cached is not None:
        return cached

    tier_count = total_cap = total_filled = racers = 0
    manifest = load_atlas_manifest(contract)
    if manifest is not None:
        tier_structure = manifest.get("tier_structure", {})
        tiers = manifest.get("tiers", [])
        fill = tier_fill_counts(db, contract)  # {tier: won count}
        tier_count = len(tiers)
        for t in tiers:
            tier = t.get("tier")
            total_cap += int((tier_structure.get(tier, {}) or {}).get("cap", 0))
            total_filled += fill.get(tier, 0)
            # Derived-window model: racers = wallets currently holding the
            # qualifying set (summed per tier, like the standings board).
            racers += len(qualified_wallets(db, contract, t))

    rollup = {
        "tier_count": tier_count,
        "total_cap": total_cap,
        "total_filled": total_filled,
        "racers": racers,
    }
    race_cache.set(key, rollup)
    return rollup


def collection_summary(db: Session, col: Collection) -> dict:
    """Directory-card rollup: collection row fields + the cached claims rollup."""
    rollup = _claims_rollup(db, col.contract_address)
    return {
        "slug": col.slug,
        "display_name": col.display_name,
        "contract_address": col.contract_address,
        "chain": col.chain,
        "image_url": col.image_url,
        "published": col.published,
        **rollup,
        "status": _status(rollup["total_cap"], rollup["total_filled"]),
    }


def list_collections(db: Session, include_unpublished: bool = False) -> list[Collection]:
    q = select(Collection).order_by(Collection.created_at.desc())
    if not include_unpublished:
        q = q.where(Collection.published.is_(True))
    return list(db.scalars(q).all())
