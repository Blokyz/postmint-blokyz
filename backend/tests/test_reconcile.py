"""Tests for app.claims.reconcile — the Claimed-event backstop.

Network-free: `_rpc` is monkeypatched. DB-backed for the recording semantics.
"""

import datetime as dt

import pytest
from eth_utils import keccak

from app.claims import reconcile as rmod
from app.claims.reconcile import NoSeason, decode_claimed_log, reconcile_claims
from app.claims.seasons import record_season
from app.db.models import Claim

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
MANAGER = "0x2222222222222222222222222222222222222222"
WALLET = "0x00000000000000000000000000000000000000a1"
TX = "0x" + "ab" * 32


def _claimed_log(tier="Rare", wallet=WALLET, slot=1, nonce=7, window_started_at=1_700_000_000, tx=TX):
    """Build a Claimed log with real ABI-encoded data:
    (string tier, uint256 slot, uint256[] tokenIds, uint256 nonce, uint256 ws)."""
    tier_b = tier.encode()
    padded_tier = tier_b + b"\x00" * (-len(tier_b) % 32)
    token_ids = [1, 2]
    # Head: [tier_offset, slot, tokenIds_offset, nonce, ws] = 5 words (160 bytes).
    tier_offset = 160
    ids_offset = tier_offset + 32 + len(padded_tier)
    head = (
        tier_offset.to_bytes(32, "big")
        + slot.to_bytes(32, "big")
        + ids_offset.to_bytes(32, "big")
        + nonce.to_bytes(32, "big")
        + window_started_at.to_bytes(32, "big")
    )
    tail = (
        len(tier_b).to_bytes(32, "big")
        + padded_tier
        + len(token_ids).to_bytes(32, "big")
        + b"".join(i.to_bytes(32, "big") for i in token_ids)
    )
    return {
        "address": MANAGER,
        "topics": [
            rmod.CLAIMED_TOPIC0,
            "0x" + keccak(text=tier).hex(),
            "0x" + "0" * 24 + wallet[2:],
        ],
        "data": "0x" + (head + tail).hex(),
        "transactionHash": tx,
        "blockNumber": hex(1234),
    }


def _mock_rpc(monkeypatch, logs):
    served = {"done": False}

    def fake(rpc_url, method, params):
        if method == "eth_blockNumber":
            return hex(500_000)
        if method == "eth_getLogs":
            # Serve everything on the first chunk (whatever the scan window),
            # nothing after.
            if served["done"]:
                return []
            served["done"] = True
            return logs
        raise AssertionError(method)

    monkeypatch.setattr(rmod, "_rpc", fake)


# --- decoding ---


def test_decode_claimed_log():
    ev = decode_claimed_log(_claimed_log(tier="Super Rare", slot=3, nonce=9, window_started_at=1_600_000_000))
    assert ev["tier"] == "Super Rare"
    assert ev["wallet"] == WALLET
    assert ev["slot_number"] == 3
    assert ev["token_ids"] == [1, 2]
    assert ev["window_started_at"] == 1_600_000_000
    assert ev["tx_hash"] == TX


# --- reconciliation ---


def test_reconcile_records_stuck_claim(db, monkeypatch):
    """A sign-created row + an on-chain event the frontend never confirmed."""
    record_season(db, CONTRACT, MANAGER, 84532)
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier="Rare",
            wallet_address=WALLET,
            window_started=dt.datetime.now(dt.timezone.utc),
            qualifying_tokens=[1, 2],
        )
    )
    db.commit()
    _mock_rpc(monkeypatch, [_claimed_log()])

    out = reconcile_claims(db, CONTRACT, "http://mock", lookback_blocks=200_000)
    db.commit()
    assert len(out["recorded"]) == 1
    row = db.query(Claim).one()
    assert row.on_chain_tx_hash == TX
    assert row.slot_number == 1
    assert row.qualifying_tokens == [1, 2]  # sign-created row reused


def test_reconcile_creates_orphan_win_row(db, monkeypatch):
    """No surviving sign row (consumed by a prior win) — the event is still
    backend-authorized proof, so a fresh won row is created."""
    record_season(db, CONTRACT, MANAGER, 84532)
    _mock_rpc(monkeypatch, [_claimed_log(slot=2, window_started_at=1_650_000_000)])

    out = reconcile_claims(db, CONTRACT, "http://mock")
    db.commit()
    assert len(out["recorded"]) == 1
    row = db.query(Claim).one()
    assert row.slot_number == 2
    assert row.on_chain_tx_hash == TX
    assert int(row.window_started.timestamp()) == 1_650_000_000
    # Set consumption: the orphan row carries the event's token ids so those
    # tokens are spent for this tier too.
    assert row.qualifying_tokens == [1, 2]


def test_reconcile_is_idempotent(db, monkeypatch):
    record_season(db, CONTRACT, MANAGER, 84532)
    _mock_rpc(monkeypatch, [_claimed_log()])
    reconcile_claims(db, CONTRACT, "http://mock")
    db.commit()

    _mock_rpc(monkeypatch, [_claimed_log()])  # chain returns the same event again
    out = reconcile_claims(db, CONTRACT, "http://mock")
    db.commit()
    assert out["recorded"] == []
    assert out["already_recorded"] == 1
    assert db.query(Claim).count() == 1


def test_reconcile_multiple_events_and_wallets(db, monkeypatch):
    record_season(db, CONTRACT, MANAGER, 84532)
    other = "0x00000000000000000000000000000000000000b2"
    _mock_rpc(
        monkeypatch,
        [
            _claimed_log(slot=1, tx="0x" + "01" * 32),
            _claimed_log(slot=2, wallet=other, tx="0x" + "02" * 32),
            _claimed_log(tier="Mythic", slot=1, tx="0x" + "03" * 32),
        ],
    )
    out = reconcile_claims(db, CONTRACT, "http://mock")
    db.commit()
    assert len(out["recorded"]) == 3
    assert db.query(Claim).count() == 3


def test_reconcile_no_season_raises(db):
    with pytest.raises(NoSeason):
        reconcile_claims(db, CONTRACT, "http://mock")


# --- API endpoint ---


def test_reconcile_endpoint(client, db, monkeypatch):
    record_season(db, CONTRACT, MANAGER, 84532)
    db.commit()
    _mock_rpc(monkeypatch, [_claimed_log()])
    r = client.post(f"/claims/reconcile/{CONTRACT}")
    assert r.status_code == 200, r.text
    assert len(r.json()["recorded"]) == 1


def test_reconcile_endpoint_404_without_season(client, db):
    r = client.post(f"/claims/reconcile/{CONTRACT}")
    assert r.status_code == 404


# --- holder-facing /claim/sync ---


def _sync(client, tier="Rare", wallet=WALLET):
    return client.post(
        "/claim/sync",
        json={"contract_address": CONTRACT, "tier": tier, "wallet_address": wallet},
    )


def test_claim_sync_recovers_stuck_win(client, db, monkeypatch):
    """The smart-account scenario: claim landed on-chain, frontend has a
    phantom hash — sync scans the chain, records the win, and reports it."""
    record_season(db, CONTRACT, MANAGER, 84532)
    db.add(
        Claim(
            contract_address=CONTRACT,
            tier="Rare",
            wallet_address=WALLET,
            window_started=dt.datetime.now(dt.timezone.utc),
        )
    )
    db.commit()
    _mock_rpc(monkeypatch, [_claimed_log()])

    r = _sync(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["won"] is True
    assert body["slot_number"] == 1
    assert body["tx_hash"] == TX


def test_claim_sync_not_won(client, db, monkeypatch):
    record_season(db, CONTRACT, MANAGER, 84532)
    db.commit()
    _mock_rpc(monkeypatch, [])
    r = _sync(client)
    assert r.status_code == 200
    assert r.json()["won"] is False


def test_claim_sync_throttles_chain_scans(client, db, monkeypatch):
    """Concurrent pollers must not each trigger a chain scan — one scan per
    contract per throttle window; later calls answer from the DB."""
    record_season(db, CONTRACT, MANAGER, 84532)
    db.commit()
    calls = []

    def fake(rpc_url, method, params):
        calls.append(method)
        if method == "eth_blockNumber":
            return hex(500_000)
        return []

    monkeypatch.setattr(rmod, "_rpc", fake)
    _sync(client)
    scans_after_first = calls.count("eth_blockNumber")
    _sync(client)
    _sync(client)
    assert calls.count("eth_blockNumber") == scans_after_first  # no re-scan


def test_claim_sync_404_without_season(client, db):
    r = _sync(client)
    assert r.status_code == 404
