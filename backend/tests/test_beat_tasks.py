"""Tests for the Celery-beat cycle functions (app.tasks.claims) and the
transfer-poller staleness health route.

DB-backed; the per-contract workers (`poll_transfers` / `reconcile_claims`) are
mocked — their own behavior is covered by test_transfers.py / test_reconcile.py.
"""

from datetime import datetime, timedelta, timezone

from app.claims.reconcile import NoSeason
from app.db.models import Collection, TransferSync
from app.tasks import claims as tasks_mod
from app.tasks.claims import poll_all_published, reconcile_all_seasons
from app.worker import celery_app

C1 = "0x00000000000000000000000000000000000000c1"
C2 = "0x00000000000000000000000000000000000000c2"
C3 = "0x00000000000000000000000000000000000000c3"


def _seed_collections(db, *, unpublished_extra=True):
    db.add(Collection(slug="one", contract_address=C1, display_name="One", chain="base-sepolia"))
    db.add(Collection(slug="two", contract_address=C2, display_name="Two", chain="base-sepolia"))
    if unpublished_extra:
        db.add(
            Collection(
                slug="draft", contract_address=C3, display_name="Draft",
                chain="base-sepolia", published=False,
            )
        )
    db.commit()


# --- poll_all_published ---


def test_poll_all_covers_published_only(db, monkeypatch):
    _seed_collections(db)
    called = []
    monkeypatch.setattr(
        tasks_mod, "poll_transfers",
        lambda _db, contract, chain: called.append((contract, chain)) or {"transfers": 0},
    )
    out = poll_all_published(db)
    assert [c for c, _ in called] == [C1, C2]  # unpublished C3 skipped
    assert set(out["polled"]) == {C1, C2}
    assert out["failed"] == {}


def test_poll_all_isolates_failures(db, monkeypatch):
    _seed_collections(db)

    def boom_first(_db, contract, chain):
        if contract == C1:
            raise RuntimeError("Moralis quota exhausted")
        return {"transfers": 3}

    monkeypatch.setattr(tasks_mod, "poll_transfers", boom_first)
    out = poll_all_published(db)
    assert "quota" in out["failed"][C1]
    assert out["polled"] == {C2: {"transfers": 3}}  # C1's failure didn't stop C2


# --- reconcile_all_seasons ---


def test_reconcile_all_skips_no_season_and_isolates_failures(db, monkeypatch):
    _seed_collections(db, unpublished_extra=False)

    def fake_reconcile(_db, contract, rpc_url, lookback_blocks):
        if contract == C1:
            raise NoSeason(contract)
        return {"recorded": [{"tier": "Common", "slot_number": 1}], "skipped": 2}

    monkeypatch.setattr(tasks_mod, "reconcile_claims", fake_reconcile)
    out = reconcile_all_seasons(db)
    assert C1 not in out["reconciled"] and C1 not in out["failed"]  # NoSeason = silent skip
    assert out["reconciled"][C2] == {"recorded": 1, "skipped": 2}


# --- beat schedule wiring ---


def test_beat_schedule_registered():
    tasks = {e["task"] for e in celery_app.conf.beat_schedule.values()}
    assert "app.tasks.claims.poll_all_transfers" in tasks
    assert "app.tasks.claims.reconcile_all" in tasks


# --- /health/poller staleness ---


def test_health_poller_staleness(client, db):
    _seed_collections(db, unpublished_extra=False)
    now = datetime.now(timezone.utc)
    # C1 polled recently; C2 has no sync row at all (never polled → stale).
    db.add(TransferSync(contract_address=C1, last_block=123, updated_at=now))
    db.commit()

    body = client.get("/health/poller").json()
    by_contract = {c["contract_address"]: c for c in body["collections"]}
    assert by_contract[C1]["stale"] is False
    assert by_contract[C1]["last_block"] == 123
    assert by_contract[C2]["stale"] is True
    assert by_contract[C2]["last_poll_at"] is None
    assert body["any_stale"] is True

    # Age C1 past the threshold → stale flips.
    db.get(TransferSync, C1).updated_at = now - timedelta(seconds=3600)
    db.commit()
    body = client.get("/health/poller").json()
    assert {c["contract_address"]: c["stale"] for c in body["collections"]} == {C1: True, C2: True}
