"""Integration tests for the /audit API routes — require a live postmint_test DB."""

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.db.models import IngestJob

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


# ── POST /audit/approve (stub) ─────────────────────────────────────────────────

def test_approve_returns_not_implemented(client):
    r = client.post("/audit/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "not_implemented"
