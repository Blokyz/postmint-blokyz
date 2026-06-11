"""Integration tests for the /audit API routes — require a live postmint_test DB."""

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models import IngestJob
from app.manifests import compute_manifest_hash

_CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d"
_CONTRACT_MIXED = "0xBC4CA0EdA7647A8aB7C2061c2E118A18a936f13D"  # mixed-case input


def _add_job(db, contract: str = _CONTRACT, status: str = "pending", manifest_path: str = None) -> IngestJob:
    job = IngestJob(
        id=str(uuid.uuid4()),
        contract_address=contract,
        chain="eth",
        status=status,
        manifest_path=manifest_path,
    )
    db.add(job)
    db.commit()
    return job


# ── GET /health ────────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_db_returns_ok(client):
    r = client.get("/health/db")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── POST /audit/ingest ─────────────────────────────────────────────────────────

def test_ingest_queues_job(client, db):
    with patch("app.api.audit.run_ingest.delay") as mock_delay:
        r = client.post("/audit/ingest", json={"contract_address": _CONTRACT_MIXED, "chain": "eth"})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["contract_address"] == _CONTRACT
    assert body["message"] == "Ingestion queued."
    mock_delay.assert_called_once_with(body["job_id"])


def test_ingest_creates_db_row(client, db):
    with patch("app.api.audit.run_ingest.delay"):
        r = client.post("/audit/ingest", json={"contract_address": _CONTRACT, "chain": "eth"})

    job_id = r.json()["job_id"]
    job = db.get(IngestJob, job_id)
    assert job is not None
    assert job.contract_address == _CONTRACT
    assert job.status == "pending"


def test_ingest_deduplicates_active_job(client, db):
    existing = _add_job(db, status="running")

    with patch("app.api.audit.run_ingest.delay") as mock_delay:
        r = client.post("/audit/ingest", json={"contract_address": _CONTRACT, "chain": "eth"})

    assert r.status_code == 200
    assert r.json()["job_id"] == existing.id
    mock_delay.assert_called_once_with(existing.id)


def test_ingest_does_not_deduplicate_failed_job(client, db):
    _add_job(db, status="failed")

    with patch("app.api.audit.run_ingest.delay") as mock_delay:
        r = client.post("/audit/ingest", json={"contract_address": _CONTRACT, "chain": "eth"})

    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    mock_delay.assert_called_once()


def test_ingest_does_not_deduplicate_complete_job(client, db):
    _add_job(db, status="complete")

    with patch("app.api.audit.run_ingest.delay") as mock_delay:
        r = client.post("/audit/ingest", json={"contract_address": _CONTRACT, "chain": "eth"})

    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    mock_delay.assert_called_once()


def test_ingest_invalid_address_rejected(client):
    r = client.post("/audit/ingest", json={"contract_address": "not-an-address", "chain": "eth"})
    assert r.status_code == 422


def test_ingest_short_hex_rejected(client):
    r = client.post("/audit/ingest", json={"contract_address": "0xabc", "chain": "eth"})
    assert r.status_code == 422


def test_ingest_no_api_key_returns_503(client, monkeypatch):
    import app.api.audit as audit_mod
    monkeypatch.setattr(audit_mod.settings, "moralis_api_key", "")
    r = client.post("/audit/ingest", json={"contract_address": _CONTRACT, "chain": "eth"})
    assert r.status_code == 503


# ── GET /audit/status/{contract} ───────────────────────────────────────────────

def test_status_returns_job(client, db):
    job = _add_job(db, status="running")
    r = client.get(f"/audit/status/{_CONTRACT}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job.id
    assert body["status"] == "running"


def test_status_no_job_returns_nulls(client):
    r = client.get(f"/audit/status/{_CONTRACT}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] is None
    assert body["status"] is None
    assert body["progress_pct"] is None


def test_status_returns_latest_job(client, db):
    _add_job(db, status="failed")
    latest = _add_job(db, status="running")
    r = client.get(f"/audit/status/{_CONTRACT}")
    assert r.json()["job_id"] == latest.id


def test_status_contract_lowercased(client, db):
    _add_job(db)
    r = client.get(f"/audit/status/{_CONTRACT_MIXED}")
    assert r.status_code == 200
    assert r.json()["contract_address"] == _CONTRACT


# ── GET /audit/ranking/{contract} ─────────────────────────────────────────────

def test_ranking_no_job_returns_404(client):
    r = client.get(f"/audit/ranking/{_CONTRACT}")
    assert r.status_code == 404


def test_ranking_pending_job_returns_404(client, db):
    _add_job(db, status="pending")
    r = client.get(f"/audit/ranking/{_CONTRACT}")
    assert r.status_code == 404


def test_ranking_complete_job_returns_manifest(client, db, tmp_path):
    manifest = {"manifest_id": "test-id", "trait_rankings": []}
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))

    _add_job(db, status="complete", manifest_path=str(manifest_file))
    r = client.get(f"/audit/ranking/{_CONTRACT}")
    assert r.status_code == 200
    assert r.json()["manifest_id"] == "test-id"


def test_ranking_missing_manifest_file_returns_500(client, db):
    _add_job(db, status="complete", manifest_path="/nonexistent/path/manifest.json")
    r = client.get(f"/audit/ranking/{_CONTRACT}")
    assert r.status_code == 500


# ── POST /audit/approve ────────────────────────────────────────────────────────

_APPROVER = "0x1234567890abcdef1234567890abcdef12345678"

_TRAITS = [
    {"trait_category": "Background", "trait_value": "Blue"},
    {"trait_category": "Background", "trait_value": "Red"},
    {"trait_category": "Eyes", "trait_value": "Laser"},
]


def _manifest_with_traits(traits=_TRAITS) -> dict:
    return {
        "manifest_id": "test-id",
        "schema_version": "1.0",
        "collection": {"contract_address": _CONTRACT, "chain": "eth", "total_supply": 100},
        "trait_rankings": [
            {
                "rank": i + 1,
                "trait_category": t["trait_category"],
                "trait_value": t["trait_value"],
                "combined_score": 1.0 - i * 0.1,
                "pinned": False,
            }
            for i, t in enumerate(traits)
        ],
        "approval": None,
    }


def _add_approvable_job(db, tmp_path, traits=_TRAITS, manifest=None):
    manifest = manifest if manifest is not None else _manifest_with_traits(traits)
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))
    return _add_job(db, status="complete", manifest_path=str(manifest_file)), manifest_file


def _load_manifest(db, contract=_CONTRACT) -> dict:
    job = db.scalar(
        select(IngestJob)
        .where(IngestJob.contract_address == contract)
        .order_by(IngestJob.created_at.desc())
    )
    return json.loads(Path(job.manifest_path).read_text())


def _approve_payload(order, approver=_APPROVER, pinned_values=()):
    return {
        "contract_address": _CONTRACT,
        "approver_address": approver,
        "trait_rankings": [
            {"trait_category": c, "trait_value": v, "pinned": v in pinned_values}
            for c, v in order
        ],
    }


def test_approve_no_completed_job_returns_404(client):
    r = client.post("/audit/approve", json=_approve_payload([(t["trait_category"], t["trait_value"]) for t in _TRAITS]))
    assert r.status_code == 404


def test_approve_reorders_and_persists(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    new_order = [("Eyes", "Laser"), ("Background", "Red"), ("Background", "Blue")]

    r = client.post("/audit/approve", json=_approve_payload(new_order, pinned_values=["Laser"]))
    assert r.status_code == 200
    body = r.json()
    assert body["contract_address"] == _CONTRACT
    assert body["approver_address"] == _APPROVER
    assert body["trait_count"] == 3
    assert body["manifest_hash"].startswith("0x") and len(body["manifest_hash"]) == 66

    saved = _load_manifest(db)
    rankings = saved["trait_rankings"]
    assert [(r["trait_category"], r["trait_value"]) for r in rankings] == new_order
    assert [r["rank"] for r in rankings] == [1, 2, 3]
    assert rankings[0]["pinned"] is True
    assert rankings[1]["pinned"] is False and rankings[2]["pinned"] is False
    assert saved["approval"]["approver_address"] == _APPROVER
    assert saved["approval"]["manifest_hash"] == body["manifest_hash"]


def test_approve_hash_is_reproducible_from_published_manifest(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    new_order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]

    r = client.post("/audit/approve", json=_approve_payload(new_order))
    assert r.status_code == 200
    manifest_hash = r.json()["manifest_hash"]

    published = json.loads(client.get(f"/audit/ranking/{_CONTRACT}").text)
    assert compute_manifest_hash(published) == manifest_hash


def test_approve_rejects_duplicate_traits(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    order = [("Background", "Blue"), ("Background", "Blue"), ("Eyes", "Laser")]

    r = client.post("/audit/approve", json=_approve_payload(order))
    assert r.status_code == 400


def test_approve_rejects_missing_trait(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    order = [("Background", "Blue"), ("Background", "Red")]  # drops "Eyes"/"Laser"

    r = client.post("/audit/approve", json=_approve_payload(order))
    assert r.status_code == 400


def test_approve_rejects_unknown_trait(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    order = [("Background", "Blue"), ("Background", "Red"), ("Eyes", "Cyclops")]

    r = client.post("/audit/approve", json=_approve_payload(order))
    assert r.status_code == 400


def test_approve_invalid_approver_address_rejected(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]

    r = client.post("/audit/approve", json=_approve_payload(order, approver="not-an-address"))
    assert r.status_code == 422
