"""Integration tests for the /audit API routes — require a live postmint_test DB."""

import json
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import select

from app.config import get_settings
from app.db.models import IngestJob
from app.manifests import compute_manifest_hash
from app.signing import build_approval_message, build_ingest_message

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


# ── POST /audit/ingest — operator authorization (enforce-when-configured) ──────
# Keys (_APPROVER_KEY / _OTHER_KEY) are defined in the approve section below;
# module globals resolve at call time so the order is harmless.

def _signed_ingest_payload(contract=_CONTRACT, chain="eth", issued_at=None, key=None, operator=None):
    key = key or _APPROVER_KEY
    issued_at = issued_at if issued_at is not None else int(time.time())
    msg = build_ingest_message(contract, chain, issued_at)
    sig = Account.sign_message(encode_defunct(text=msg), private_key=key).signature.hex()
    return {
        "contract_address": contract,
        "chain": chain,
        "operator_address": operator or Account.from_key(key).address.lower(),
        "signature": sig if sig.startswith("0x") else "0x" + sig,
        "issued_at": issued_at,
    }


def test_ingest_authorized_when_signer_allowlisted(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "operator_allowlist", _APPROVER)
    with patch("app.api.audit.run_ingest.delay"):
        r = client.post("/audit/ingest", json=_signed_ingest_payload())
    assert r.status_code == 200, r.text


def test_ingest_rejected_when_signer_not_allowlisted(client, db, monkeypatch):
    """Validly signed but not an operator → authenticated, not authorized (403)."""
    monkeypatch.setattr(get_settings(), "operator_allowlist", _OTHER_ADDRESS)
    r = client.post("/audit/ingest", json=_signed_ingest_payload())  # signed by _APPROVER
    assert r.status_code == 403


def test_ingest_unsigned_rejected_when_gated(client, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "operator_allowlist", _APPROVER)
    r = client.post("/audit/ingest", json={"contract_address": _CONTRACT, "chain": "eth"})
    assert r.status_code == 401


def test_ingest_stale_signature_rejected(client, db, monkeypatch):
    """issued_at older than the TTL → the captured signature has gone stale."""
    monkeypatch.setattr(get_settings(), "operator_allowlist", _APPROVER)
    stale = int(time.time()) - get_settings().ingest_sig_ttl_seconds - 60
    r = client.post("/audit/ingest", json=_signed_ingest_payload(issued_at=stale))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_ingest_forged_operator_address_rejected(client, db, monkeypatch):
    """Claims the allowlisted operator but signs with a different key — the
    recovered signer won't match, so the request is rejected (the forgery a
    plain address field would allow)."""
    monkeypatch.setattr(get_settings(), "operator_allowlist", _APPROVER)
    r = client.post("/audit/ingest", json=_signed_ingest_payload(key=_OTHER_KEY, operator=_APPROVER))
    assert r.status_code == 401


def test_ingest_tampered_chain_rejected(client, db, monkeypatch):
    """Sign for one chain, submit another — the message changes, recovery fails."""
    monkeypatch.setattr(get_settings(), "operator_allowlist", _APPROVER)
    payload = _signed_ingest_payload(chain="eth")
    payload["chain"] = "base"
    r = client.post("/audit/ingest", json=payload)
    assert r.status_code == 401


# ── Concurrent-ingest race (Wave 3) ────────────────────────────────────────────

def test_unique_active_job_index_enforced(db):
    from sqlalchemy.exc import IntegrityError

    _add_job(db, status="running")
    with pytest.raises(IntegrityError):
        _add_job(db, status="pending")
    db.rollback()


def test_failed_and_complete_jobs_do_not_block_new_active(db):
    _add_job(db, status="failed")
    _add_job(db, status="complete")
    _add_job(db, status="pending")  # must not raise


def test_ingest_race_lost_insert_resumes_winner(client, db):
    """Simulate losing the check-then-insert race: the winner's active job lands
    after our no-active-job check but before our commit. The unique index rejects
    our insert and the endpoint must hand back the winner's job as a resume."""
    from app.api import audit as audit_mod

    winner = _add_job(db, status="running")
    real_active_job = audit_mod._active_job
    calls = {"n": 0}

    def racy_active_job(db_, contract):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # the pre-insert check ran before the winner committed
        return real_active_job(db_, contract)

    with patch("app.api.audit._active_job", side_effect=racy_active_job), \
         patch("app.api.audit.run_ingest.delay") as mock_delay:
        r = client.post("/audit/ingest", json={"contract_address": _CONTRACT, "chain": "eth"})

    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == winner.id
    assert "re-queued" in body["message"]
    mock_delay.assert_called_once_with(winner.id)


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

# Deterministic test keys; addresses are derived so the recovered signer matches.
_APPROVER_KEY = "0x" + "11" * 32
_OTHER_KEY = "0x" + "22" * 32
_APPROVER = Account.from_key(_APPROVER_KEY).address.lower()
_OTHER_ADDRESS = Account.from_key(_OTHER_KEY).address.lower()


def _sign(contract, trait_rankings, w_stat=0.5, w_market=0.5, key=_APPROVER_KEY) -> str:
    ordered = [(t["trait_category"], t["trait_value"], t["pinned"]) for t in trait_rankings]
    message = build_approval_message(contract, ordered, w_stat, w_market)
    sig = Account.sign_message(encode_defunct(text=message), private_key=key).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig

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


def _approve_payload(
    order, approver=_APPROVER, pinned_values=(), sign_key=_APPROVER_KEY,
    signature=None, w_stat=0.5, w_market=0.5,
):
    trait_rankings = [
        {"trait_category": c, "trait_value": v, "pinned": v in pinned_values}
        for c, v in order
    ]
    return {
        "contract_address": _CONTRACT,
        "approver_address": approver,
        "trait_rankings": trait_rankings,
        "w_stat": w_stat,
        "w_market": w_market,
        "signature": signature if signature is not None
        else _sign(_CONTRACT, trait_rankings, w_stat, w_market, sign_key),
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


# ── POST /audit/approve — signature authentication ──────────────────────────────

def test_approve_forged_signature_rejected(client, db, tmp_path):
    """Claims _APPROVER but signs with a different key — the recovered signer
    won't match, so the approval is rejected (this is the forgery the field-only
    version allowed)."""
    _add_approvable_job(db, tmp_path)
    order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]

    r = client.post("/audit/approve", json=_approve_payload(order, approver=_APPROVER, sign_key=_OTHER_KEY))
    assert r.status_code == 401


def test_approve_authorized_when_signer_allowlisted(client, db, tmp_path, monkeypatch):
    """With the allowlist configured, an approval from a listed signer succeeds."""
    monkeypatch.setattr(get_settings(), "operator_allowlist", _APPROVER)
    _add_approvable_job(db, tmp_path)
    order = [("Eyes", "Laser"), ("Background", "Red"), ("Background", "Blue")]
    r = client.post("/audit/approve", json=_approve_payload(order, pinned_values=["Laser"]))
    assert r.status_code == 200, r.text


def test_approve_rejected_when_signer_not_allowlisted(client, db, tmp_path, monkeypatch):
    """A validly-signed approval from a non-operator is authenticated but not
    authorized → 403 (authN vs authZ)."""
    monkeypatch.setattr(get_settings(), "operator_allowlist", _OTHER_ADDRESS)
    _add_approvable_job(db, tmp_path)
    order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]
    r = client.post("/audit/approve", json=_approve_payload(order))  # signed by _APPROVER
    assert r.status_code == 403


def test_approve_tampered_order_rejected(client, db, tmp_path):
    """Sign one order, submit a different one — the message changes so the
    recovered signer no longer matches approver_address."""
    _add_approvable_job(db, tmp_path)
    payload = _approve_payload([(t["trait_category"], t["trait_value"]) for t in _TRAITS])
    # Reorder after signing without re-signing.
    payload["trait_rankings"] = list(reversed(payload["trait_rankings"]))

    r = client.post("/audit/approve", json=payload)
    assert r.status_code == 401


def test_approve_tampered_pinned_rejected(client, db, tmp_path):
    """Flipping a pinned flag after signing invalidates the signature."""
    _add_approvable_job(db, tmp_path)
    payload = _approve_payload([(t["trait_category"], t["trait_value"]) for t in _TRAITS])
    payload["trait_rankings"][0]["pinned"] = True

    r = client.post("/audit/approve", json=payload)
    assert r.status_code == 401


def test_approve_short_signature_rejected(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]

    r = client.post("/audit/approve", json=_approve_payload(order, signature="0xdeadbeef"))
    assert r.status_code == 422


def test_approve_undecodable_signature_rejected(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]

    r = client.post("/audit/approve", json=_approve_payload(order, signature="0x" + "00" * 65))
    assert r.status_code == 400


# ── POST /audit/approve — α/β weight blending ───────────────────────────────────

def test_approve_reblends_combined_score_with_weights(client, db, tmp_path):
    """The approver's chosen weights re-blend combined_score = w_stat*stat_norm
    + w_market*market_norm and are persisted to the manifest."""
    manifest = _manifest_with_traits()
    for row in manifest["trait_rankings"]:
        row["stat_norm"] = 0.8
        row["market_norm"] = 0.2
    _add_approvable_job(db, tmp_path, manifest=manifest)
    order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]

    r = client.post("/audit/approve", json=_approve_payload(order, w_stat=0.75, w_market=0.25))
    assert r.status_code == 200
    assert r.json()["w_stat"] == 0.75 and r.json()["w_market"] == 0.25

    saved = _load_manifest(db)
    assert saved["weights"] == {"w_stat": 0.75, "w_market": 0.25}
    for row in saved["trait_rankings"]:
        # 0.75 * 0.8 + 0.25 * 0.2 = 0.65
        assert row["combined_score"] == pytest.approx(0.65)


def test_approve_tampered_weights_rejected(client, db, tmp_path):
    """Weights are covered by the signature: signing 0.5/0.5 then submitting
    different weights fails recovery."""
    _add_approvable_job(db, tmp_path)
    payload = _approve_payload([(t["trait_category"], t["trait_value"]) for t in _TRAITS])
    payload["w_stat"] = 0.7  # signed with 0.5/0.5
    payload["w_market"] = 0.3

    r = client.post("/audit/approve", json=payload)
    assert r.status_code == 401


def test_approve_weights_not_summing_to_one_rejected(client, db, tmp_path):
    _add_approvable_job(db, tmp_path)
    order = [(t["trait_category"], t["trait_value"]) for t in _TRAITS]

    r = client.post("/audit/approve", json=_approve_payload(order, w_stat=0.7, w_market=0.7))
    assert r.status_code == 422
