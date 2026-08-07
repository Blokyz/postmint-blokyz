"""Tests for app.claims.acquisitions — lazy acquired_at backfill + set-completion.

DB-backed; Moralis is mocked via monkeypatching `fetch_wallet_transfers_page`.
"""

import datetime as dt

from app.claims import acquisitions as amod
from app.claims.acquisitions import ensure_acquired_at, set_completed_at
from app.db.models import Token
from app.ingestion.moralis_client import TransfersPage

CONTRACT = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
WALLET = "0x00000000000000000000000000000000000000a1"
OTHER = "0x00000000000000000000000000000000000000ff"

T_JAN = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
T_FEB = dt.datetime(2026, 2, 10, tzinfo=dt.timezone.utc)
T_JUL = dt.datetime(2026, 7, 10, tzinfo=dt.timezone.utc)


def _seed_tokens(db, count, owner=WALLET, acquired_at=None):
    for token_id in range(1, count + 1):
        db.add(
            Token(
                contract_address=CONTRACT,
                token_id=token_id,
                owner_address=owner,
                acquired_at=acquired_at,
            )
        )
    db.commit()


def _xfer(token_id, to, acquired_at, frm=OTHER):
    return {
        "token_id": token_id,
        "from_address": frm,
        "to_address": to,
        "block_number": 100,
        "log_index": 0,
        "tx_hash": "0x" + "aa" * 32,
        "acquired_at": acquired_at,
    }


def _mock_pages(monkeypatch, pages: list[TransfersPage]):
    calls = {"n": 0}

    def fake(wallet, contract, chain, api_key, cursor=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page

    monkeypatch.setattr(amod, "fetch_wallet_transfers_page", fake)
    return calls


# --- ensure_acquired_at ---


def test_backfill_fills_nulls_from_history(db, monkeypatch):
    _seed_tokens(db, 2)
    _mock_pages(
        monkeypatch,
        [TransfersPage(transfers=[_xfer(2, WALLET, T_FEB), _xfer(1, WALLET, T_JAN)], next_cursor=None)],
    )
    stamped = ensure_acquired_at(db, CONTRACT, WALLET, chain="base", api_key="k")
    db.commit()
    assert stamped == 2
    assert db.get(Token, (CONTRACT, 1)).acquired_at == T_JAN
    assert db.get(Token, (CONTRACT, 2)).acquired_at == T_FEB


def test_backfill_newest_inbound_wins(db, monkeypatch):
    """History is walked newest-first; a sell-and-rebuy must count from the
    rebuy (first inbound seen), not the original purchase deeper in history."""
    _seed_tokens(db, 1)
    _mock_pages(
        monkeypatch,
        [
            TransfersPage(
                transfers=[
                    _xfer(1, WALLET, T_JUL),          # rebuy (newest)
                    _xfer(1, OTHER, T_FEB, frm=WALLET),  # the sale
                    _xfer(1, WALLET, T_JAN),          # original purchase
                ],
                next_cursor=None,
            )
        ],
    )
    ensure_acquired_at(db, CONTRACT, WALLET, chain="base", api_key="k")
    db.commit()
    assert db.get(Token, (CONTRACT, 1)).acquired_at == T_JUL


def test_backfill_noop_when_all_stamped(db, monkeypatch):
    _seed_tokens(db, 2, acquired_at=T_JAN)

    def boom(*args, **kwargs):  # pragma: no cover
        raise AssertionError("Moralis must not be called when nothing is missing")

    monkeypatch.setattr(amod, "fetch_wallet_transfers_page", boom)
    assert ensure_acquired_at(db, CONTRACT, WALLET, chain="base", api_key="k") == 0


def test_backfill_ignores_outbound_and_other_wallets(db, monkeypatch):
    _seed_tokens(db, 1)
    _mock_pages(
        monkeypatch,
        [
            TransfersPage(
                transfers=[_xfer(1, OTHER, T_FEB, frm=WALLET), _xfer(1, WALLET, T_JAN)],
                next_cursor=None,
            )
        ],
    )
    ensure_acquired_at(db, CONTRACT, WALLET, chain="base", api_key="k")
    db.commit()
    assert db.get(Token, (CONTRACT, 1)).acquired_at == T_JAN


def test_backfill_unresolved_stamped_now(db, monkeypatch):
    """History exhausted without finding the token -> conservative 'now' stamp
    (the clock starts today; a fresh buyer can never skip the wait)."""
    _seed_tokens(db, 1)
    _mock_pages(monkeypatch, [TransfersPage(transfers=[], next_cursor=None)])
    before = dt.datetime.now(dt.timezone.utc)
    stamped = ensure_acquired_at(db, CONTRACT, WALLET, chain="base", api_key="k")
    db.commit()
    after = dt.datetime.now(dt.timezone.utc)
    assert stamped == 1
    acquired = db.get(Token, (CONTRACT, 1)).acquired_at
    assert before <= acquired <= after


def test_backfill_stops_at_page_cap(db, monkeypatch):
    _seed_tokens(db, 1)
    endless = TransfersPage(transfers=[_xfer(999, WALLET, T_JAN)], next_cursor="more")
    calls = _mock_pages(monkeypatch, [endless] * 3)
    ensure_acquired_at(db, CONTRACT, WALLET, chain="base", api_key="k", max_pages=3)
    db.commit()
    assert calls["n"] == 3
    assert db.get(Token, (CONTRACT, 1)).acquired_at is not None  # stamped now


# --- set_completed_at ---


def test_set_completed_at_is_xth_oldest(db):
    """Needing 2 of tokens acquired Jan/Feb/Jul, the set was complete in Feb."""
    _seed_tokens(db, 3)
    for token_id, ts in [(1, T_JAN), (2, T_FEB), (3, T_JUL)]:
        db.get(Token, (CONTRACT, token_id)).acquired_at = ts
    db.commit()
    assert set_completed_at(db, CONTRACT, WALLET, [1, 2, 3], count_required=2) == T_FEB
    assert set_completed_at(db, CONTRACT, WALLET, [1, 2, 3], count_required=3) == T_JUL


def test_set_completed_at_insufficient_holdings(db):
    _seed_tokens(db, 1, acquired_at=T_JAN)
    assert set_completed_at(db, CONTRACT, WALLET, [1], count_required=2) is None
    assert set_completed_at(db, CONTRACT, WALLET, [1], count_required=0) is None


def test_set_completed_at_null_counts_as_now(db):
    """An unstamped token can't shorten the wait — it pushes completion to now."""
    _seed_tokens(db, 2)
    db.get(Token, (CONTRACT, 1)).acquired_at = T_JAN
    db.commit()  # token 2 stays NULL
    before = dt.datetime.now(dt.timezone.utc)
    completed = set_completed_at(db, CONTRACT, WALLET, [1, 2], count_required=2)
    after = dt.datetime.now(dt.timezone.utc)
    assert before <= completed <= after
