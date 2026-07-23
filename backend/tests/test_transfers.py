"""Tests for app.claims.transfers — the holding-window transfer poller.

DB-backed; Moralis is mocked via monkeypatching `fetch_transfers_page`.
"""

import pytest

from app.claims import transfers as tmod
from app.claims.transfers import apply_transfer_ownership, poll_transfers
from app.db.models import Claim, Token, Trait, TransferSync
from app.ingestion.moralis_client import TransfersPage

CONTRACT = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
WALLET = "0x00000000000000000000000000000000000000a1"
BUYER = "0x00000000000000000000000000000000000000ff"


def _manifest(window_hours=72, count_required=2):
    return {
        "tier_structure": {"Rare": {"cap": 500, "holding_window_hours": window_hours}},
        "tiers": [
            {
                "tier": "Rare",
                "set_rule": {
                    "archetype": "count_of_pool",
                    "pool": [{"trait_category": "Hat", "trait_value": "Gold"}],
                    "count_required": count_required,
                },
            }
        ],
    }


def _seed_holdings(db, count):
    for token_id in range(1, count + 1):
        db.add(Token(contract_address=CONTRACT, token_id=token_id, owner_address=WALLET))
        db.add(Trait(contract_address=CONTRACT, token_id=token_id, trait_category="Hat", trait_value="Gold"))
    db.commit()


def _xfer(token_id, frm, to, block, log_index=0):
    return {
        "token_id": token_id,
        "from_address": frm,
        "to_address": to,
        "block_number": block,
        "log_index": log_index,
        "tx_hash": "0x" + "aa" * 32,
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


# --- full poll cycle ---


def test_poll_resets_window_on_out_transfer(db, monkeypatch):
    _seed_holdings(db, 2)
    # Start a window (holds 2, needs 2).
    row = Claim(
        contract_address=CONTRACT, tier="Rare", wallet_address=WALLET,
        window_started=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        qualifying_tokens=[1, 2],
    )
    db.add(row)
    db.commit()

    # token 2 leaves WALLET -> drops to 1 < X -> window should reset.
    _mock_pages(monkeypatch, [TransfersPage(transfers=[_xfer(2, WALLET, BUYER, 500)], next_cursor=None)])
    summary = poll_transfers(db, CONTRACT, "base", _manifest(), api_key="k")
    db.commit()

    assert summary["tokens_updated"] == 1
    assert summary["windows_reset"] == [{"wallet": WALLET, "tier": "Rare"}]
    assert summary["last_block"] == 500
    assert db.get(Token, (CONTRACT, 2)).owner_address == BUYER
    assert db.query(Claim).one().window_started is None


def test_poll_keeps_window_when_still_qualified(db, monkeypatch):
    _seed_holdings(db, 3)  # holds 3, needs 2
    import datetime as dt
    row = Claim(
        contract_address=CONTRACT, tier="Rare", wallet_address=WALLET,
        window_started=dt.datetime.now(dt.timezone.utc), qualifying_tokens=[1, 2, 3],
    )
    db.add(row)
    db.commit()

    _mock_pages(monkeypatch, [TransfersPage(transfers=[_xfer(3, WALLET, BUYER, 600)], next_cursor=None)])
    summary = poll_transfers(db, CONTRACT, "base", _manifest(count_required=2), api_key="k")
    db.commit()

    assert summary["windows_reset"] == []
    assert db.query(Claim).one().window_started is not None


def test_poll_advances_high_water_block_and_paginates(db, monkeypatch):
    _seed_holdings(db, 2)
    _mock_pages(
        monkeypatch,
        [
            TransfersPage(transfers=[_xfer(1, WALLET, BUYER, 700)], next_cursor="c1"),
            TransfersPage(transfers=[_xfer(2, BUYER, WALLET, 710)], next_cursor=None),
        ],
    )
    summary = poll_transfers(db, CONTRACT, "base", _manifest(), api_key="k")
    db.commit()

    assert summary["pages"] == 2
    assert summary["transfers"] == 2
    assert summary["last_block"] == 710
    assert summary["drained"] is True
    assert db.get(TransferSync, CONTRACT).last_block == 710


def test_poll_no_transfers_is_noop(db, monkeypatch):
    _seed_holdings(db, 2)
    _mock_pages(monkeypatch, [TransfersPage(transfers=[], next_cursor=None)])
    summary = poll_transfers(db, CONTRACT, "base", _manifest(), api_key="k")
    db.commit()
    assert summary["transfers"] == 0
    assert summary["tokens_updated"] == 0
    assert summary["windows_reset"] == []
