"""Tests for app.claims.transfers — the ownership/acquisition transfer poller.

DB-backed; Moralis is mocked via monkeypatching `fetch_transfers_page`.
"""

import pytest

from app.claims import transfers as tmod
from app.claims.transfers import apply_transfer_ownership, poll_transfers
from app.db.models import Token, Trait, TransferSync
from app.ingestion.moralis_client import TransfersPage

CONTRACT = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
WALLET = "0x00000000000000000000000000000000000000a1"
BUYER = "0x00000000000000000000000000000000000000ff"


def _seed_holdings(db, count):
    for token_id in range(1, count + 1):
        db.add(Token(contract_address=CONTRACT, token_id=token_id, owner_address=WALLET))
        db.add(Trait(contract_address=CONTRACT, token_id=token_id, trait_category="Hat", trait_value="Gold"))
    db.commit()


def _xfer(token_id, frm, to, block, log_index=0, acquired_at=None):
    return {
        "token_id": token_id,
        "from_address": frm,
        "to_address": to,
        "block_number": block,
        "log_index": log_index,
        "tx_hash": "0x" + "aa" * 32,
        "acquired_at": acquired_at,
    }


def _mock_pages(monkeypatch, pages: list[TransfersPage]):
    calls = iter(pages)

    def fake(contract, chain, api_key, cursor=None, from_block=None):
        return next(calls)

    monkeypatch.setattr(tmod, "fetch_transfers_page", fake)


# --- ownership application (order / last-write-wins) ---


def test_apply_ownership_last_write_wins(db):
    _seed_holdings(db, 1)
    # token 1 moves WALLET->BUYER->WALLET chronologically; final owner is WALLET.
    updated = apply_transfer_ownership(
        db,
        CONTRACT,
        [_xfer(1, WALLET, BUYER, 100), _xfer(1, BUYER, WALLET, 101)],
    )
    db.commit()
    assert updated == 1
    assert db.get(Token, (CONTRACT, 1)).owner_address == WALLET


def test_apply_ownership_skips_unknown_tokens(db):
    _seed_holdings(db, 1)
    updated = apply_transfer_ownership(db, CONTRACT, [_xfer(999, WALLET, BUYER, 100)])
    assert updated == 0


# --- acquired_at (holding windows derive from it) ---


def test_apply_ownership_writes_acquired_at(db):
    import datetime as dt

    _seed_holdings(db, 1)
    ts = dt.datetime(2026, 8, 1, 12, 0, tzinfo=dt.timezone.utc)
    apply_transfer_ownership(db, CONTRACT, [_xfer(1, WALLET, BUYER, 100, acquired_at=ts)])
    db.commit()
    token = db.get(Token, (CONTRACT, 1))
    assert token.owner_address == BUYER
    assert token.acquired_at == ts


def test_apply_ownership_last_transfer_timestamp_wins(db):
    import datetime as dt

    _seed_holdings(db, 1)
    t1 = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2026, 8, 2, tzinfo=dt.timezone.utc)
    apply_transfer_ownership(
        db,
        CONTRACT,
        [_xfer(1, WALLET, BUYER, 100, acquired_at=t1), _xfer(1, BUYER, WALLET, 101, acquired_at=t2)],
    )
    db.commit()
    token = db.get(Token, (CONTRACT, 1))
    assert token.owner_address == WALLET
    assert token.acquired_at == t2


def test_apply_ownership_clears_stale_acquired_at(db):
    """An ownership change without a timestamp must NULL acquired_at, never leave
    the previous owner's timestamp crediting the buyer with old holding time."""
    import datetime as dt

    _seed_holdings(db, 1)
    token = db.get(Token, (CONTRACT, 1))
    token.acquired_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    db.commit()

    apply_transfer_ownership(db, CONTRACT, [_xfer(1, WALLET, BUYER, 100)])
    db.commit()
    token = db.get(Token, (CONTRACT, 1))
    assert token.owner_address == BUYER
    assert token.acquired_at is None


# --- full poll cycle ---


def test_poll_updates_ownership_and_timestamp(db, monkeypatch):
    import datetime as dt

    _seed_holdings(db, 2)
    ts = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
    _mock_pages(
        monkeypatch,
        [TransfersPage(transfers=[_xfer(2, WALLET, BUYER, 500, acquired_at=ts)], next_cursor=None)],
    )
    summary = poll_transfers(db, CONTRACT, "base", api_key="k")
    db.commit()

    assert summary["tokens_updated"] == 1
    assert summary["last_block"] == 500
    token = db.get(Token, (CONTRACT, 2))
    assert token.owner_address == BUYER
    assert token.acquired_at == ts


def test_poll_advances_high_water_block_and_paginates(db, monkeypatch):
    _seed_holdings(db, 2)
    _mock_pages(
        monkeypatch,
        [
            TransfersPage(transfers=[_xfer(1, WALLET, BUYER, 700)], next_cursor="c1"),
            TransfersPage(transfers=[_xfer(2, BUYER, WALLET, 710)], next_cursor=None),
        ],
    )
    summary = poll_transfers(db, CONTRACT, "base", api_key="k")
    db.commit()

    assert summary["pages"] == 2
    assert summary["transfers"] == 2
    assert summary["last_block"] == 710
    assert summary["drained"] is True
    assert db.get(TransferSync, CONTRACT).last_block == 710


def test_poll_no_transfers_is_noop(db, monkeypatch):
    _seed_holdings(db, 2)
    _mock_pages(monkeypatch, [TransfersPage(transfers=[], next_cursor=None)])
    summary = poll_transfers(db, CONTRACT, "base", api_key="k")
    db.commit()
    assert summary["transfers"] == 0
    assert summary["tokens_updated"] == 0
