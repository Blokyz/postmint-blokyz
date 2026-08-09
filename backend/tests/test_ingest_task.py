"""Integration tests for the Celery ingest task.

Calls run_ingest.apply() synchronously (no broker needed).
Moralis HTTP calls are mocked via unittest.mock.patch.
The task uses SessionLocal() which points to postmint_test (set by conftest env override).
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import IngestJob, Trait, Token
from app.ingestion.moralis_client import NftPage
from app.manifests import load_ranking_manifest
from app.tasks.ingest import run_ingest

_EMPTY_PAGE = NftPage(tokens=[], traits=[], next_cursor=None, total=0)

_CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d"


@pytest.fixture(autouse=True)
def _stub_sales_fetch(monkeypatch):
    """The per-test `with patch(...)` blocks only mock fetch_nft_page, so the
    task's sales loop would otherwise call the REAL fetch_sales_page over HTTP —
    which blocks/retries for minutes against the fake test key (this was the
    long-standing "ingest test hangs" issue). Stub it to an empty page; tests
    that need specific sales can re-patch it themselves.
    """
    from app.ingestion.moralis_client import SalesPage

    monkeypatch.setattr(
        "app.tasks.ingest.fetch_sales_page",
        lambda *args, **kwargs: SalesPage(sales=[], next_cursor=None, total=0),
    )

# Two pages of fake Moralis data: page 1 has a cursor, page 2 does not.
_PAGE_1 = NftPage(
    tokens=[
        {"contract_address": _CONTRACT, "token_id": 1, "owner_address": "0xaaa", "snapshot_block": 100},
        {"contract_address": _CONTRACT, "token_id": 2, "owner_address": "0xbbb", "snapshot_block": 100},
    ],
    traits=[
        {"contract_address": _CONTRACT, "token_id": 1, "trait_category": "Fur", "trait_value": "Gold"},
        {"contract_address": _CONTRACT, "token_id": 2, "trait_category": "Fur", "trait_value": "Brown"},
    ],
    next_cursor="page-2-cursor",
    total=3,
)

_PAGE_2 = NftPage(
    tokens=[
        {"contract_address": _CONTRACT, "token_id": 3, "owner_address": "0xccc", "snapshot_block": 101},
    ],
    traits=[
        {"contract_address": _CONTRACT, "token_id": 3, "trait_category": "Fur", "trait_value": "Blue"},
    ],
    next_cursor=None,
    total=3,
)


def _make_job(db, status: str = "pending", cursor: str = None) -> IngestJob:
    job = IngestJob(
        id=str(uuid.uuid4()),
        contract_address=_CONTRACT,
        chain="eth",
        status=status,
        last_cursor=cursor,
    )
    db.add(job)
    db.commit()
    return job


def _verify_session(test_engine):
    """Fresh session for post-task verification (sees task-committed data)."""
    Session = sessionmaker(bind=test_engine)
    return Session()


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_run_ingest_sets_status_complete(db, test_engine):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_1, _PAGE_2]):
        run_ingest.apply(args=[job.id])

    vs = _verify_session(test_engine)
    result = vs.get(IngestJob, job.id)
    assert result.status == "complete"
    assert result.progress_pct == 100
    vs.close()


def test_run_ingest_persists_all_tokens(db, test_engine):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_1, _PAGE_2]):
        run_ingest.apply(args=[job.id])

    vs = _verify_session(test_engine)
    count = vs.scalar(
        select(func.count()).select_from(Token).where(Token.contract_address == _CONTRACT)
    )
    assert count == 3
    vs.close()


def test_run_ingest_persists_all_traits(db, test_engine):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_1, _PAGE_2]):
        run_ingest.apply(args=[job.id])

    vs = _verify_session(test_engine)
    count = vs.scalar(
        select(func.count()).select_from(Trait).where(Trait.contract_address == _CONTRACT)
    )
    assert count == 3
    vs.close()


def test_run_ingest_writes_manifest(db):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_1, _PAGE_2]):
        run_ingest.apply(args=[job.id])

    assert load_ranking_manifest(_CONTRACT) is not None


def test_run_ingest_manifest_has_all_traits(db):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_1, _PAGE_2]):
        run_ingest.apply(args=[job.id])

    data = load_ranking_manifest(_CONTRACT)
    # 3 tokens all with "Fur" trait but different values → 3 distinct (category, value) pairs
    assert len(data["trait_rankings"]) == 3


def test_run_ingest_stores_manifest_path(db, test_engine):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_1, _PAGE_2]):
        run_ingest.apply(args=[job.id])

    vs = _verify_session(test_engine)
    result = vs.get(IngestJob, job.id)
    assert result.manifest_path is not None
    assert result.manifest_path.startswith("db://")
    vs.close()


def test_run_ingest_manifest_collection_fields(db):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_1, _PAGE_2]):
        run_ingest.apply(args=[job.id])

    data = load_ranking_manifest(_CONTRACT)
    assert data["collection"]["contract_address"] == _CONTRACT
    assert data["collection"]["total_supply"] == 3
    assert data["collection"]["eligible_supply"] == 3


# ── Resume on crash (cursor) ───────────────────────────────────────────────────

def test_run_ingest_resumes_from_cursor(db):
    """Task should pass stored cursor to first fetch_nft_page call."""
    job = _make_job(db, cursor="saved-cursor")

    with patch("app.tasks.ingest.fetch_nft_page", side_effect=[_PAGE_2]) as mock_fetch:
        run_ingest.apply(args=[job.id])

    first_call_cursor = mock_fetch.call_args_list[0][0][3]  # positional arg index 3
    assert first_call_cursor == "saved-cursor"


# ── Missing job ────────────────────────────────────────────────────────────────

def test_run_ingest_missing_job_does_not_raise():
    """If job_id doesn't exist, the task should log and return without raising."""
    with patch("app.tasks.ingest.fetch_nft_page") as mock_fetch:
        run_ingest.apply(args=["nonexistent-job-id"])
    mock_fetch.assert_not_called()


def test_run_ingest_empty_collection_marks_failed(db, test_engine):
    job = _make_job(db)

    with patch("app.tasks.ingest.fetch_nft_page", return_value=_EMPTY_PAGE):
        run_ingest.apply(args=[job.id])

    vs = _verify_session(test_engine)
    result = vs.get(IngestJob, job.id)
    assert result.status == "failed"
    assert "0 NFTs" in (result.error_message or "")
    vs.close()
