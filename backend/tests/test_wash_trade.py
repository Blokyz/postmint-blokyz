"""Per-rule unit tests for wash trade detection.

Each test inserts a minimal set of Sale rows into the test DB,
runs flag_wash_trades, and asserts exactly the right rows are flagged.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Sale
from app.wash_trade import WashSummary, flag_wash_trades

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d"
T0 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
# Reference time passed to flag_wash_trades so the cluster window covers T0-era trades.
_REF = T0 + timedelta(days=1)


def _sale(token_id: int, seller: str, buyer: str, price: float, sold_at=T0, tx_suffix="") -> Sale:
    tx = f"0x{'ab' * 31}{token_id:02d}{tx_suffix}"
    return Sale(
        contract_address=CONTRACT,
        token_id=token_id,
        sale_price_eth=price,
        seller_address=seller,
        buyer_address=buyer,
        sold_at=sold_at,
        tx_hash=tx,
    )


def _flag(db, contract=CONTRACT):
    """Run detection with the cluster window anchored to _REF so T0-era trades are included."""
    return flag_wash_trades(db, contract, _cluster_ref_time=_REF)


# ── Rule 1: self-trade ────────────────────────────────────────────────────────

def test_self_trade_flagged(db):
    sale = _sale(1, "0xaaa", "0xaaa", 1.0)
    db.add(sale)
    db.commit()

    summary = _flag(db)

    assert summary.self_trade == 1
    db.refresh(sale)
    assert sale.wash_trade_flag is True


def test_self_trade_different_wallets_not_flagged(db):
    sale = _sale(1, "0xaaa", "0xbbb", 1.0)
    db.add(sale)
    db.commit()

    summary = _flag(db)

    assert summary.self_trade == 0
    db.refresh(sale)
    assert sale.wash_trade_flag is False


def test_self_trade_case_insensitive(db):
    sale = _sale(1, "0xAAA", "0xaaa", 1.0)
    db.add(sale)
    db.commit()

    summary = _flag(db)

    assert summary.self_trade == 1


# ── Rule 2: rapid round-trip (24 h window) ────────────────────────────────────

def test_round_trip_within_window_flagged(db):
    a_to_b = _sale(1, "0xaaa", "0xbbb", 1.0, T0, "1")
    b_to_a = _sale(1, "0xbbb", "0xaaa", 1.2, T0 + timedelta(hours=12), "2")
    db.add_all([a_to_b, b_to_a])
    db.commit()

    summary = _flag(db)

    assert summary.round_trip == 2
    db.refresh(a_to_b)
    db.refresh(b_to_a)
    assert a_to_b.wash_trade_flag is True
    assert b_to_a.wash_trade_flag is True


def test_round_trip_outside_window_not_flagged(db):
    a_to_b = _sale(1, "0xaaa", "0xbbb", 1.0, T0, "1")
    b_to_a = _sale(1, "0xbbb", "0xaaa", 1.2, T0 + timedelta(hours=25), "2")
    db.add_all([a_to_b, b_to_a])
    db.commit()

    summary = _flag(db)

    assert summary.round_trip == 0


def test_round_trip_different_tokens_not_flagged(db):
    a_to_b = _sale(1, "0xaaa", "0xbbb", 1.0, T0, "1")
    b_to_a = _sale(2, "0xbbb", "0xaaa", 1.2, T0 + timedelta(hours=1), "2")
    db.add_all([a_to_b, b_to_a])
    db.commit()

    summary = _flag(db)

    assert summary.round_trip == 0


# ── Rule 3: recycled wallet cluster (6+ trades, ≤3 wallets, 30-day window) ───

def test_cluster_flagged(db):
    # Token 1: 7 trades between only 2 wallets — well above min_trades=6
    trades = [
        _sale(1, "0xaaa", "0xbbb", 1.0, T0 + timedelta(hours=i), str(i))
        for i in range(7)
    ]
    db.add_all(trades)
    db.commit()

    summary = _flag(db)

    assert summary.cluster == 7
    for t in trades:
        db.refresh(t)
        assert t.wash_trade_flag is True


def test_cluster_many_wallets_not_flagged(db):
    # Token 1: 7 trades each with a unique buyer — 8 distinct wallets
    trades = [
        _sale(1, "0xaaa", f"0x{i:040x}", 1.0, T0 + timedelta(hours=i), str(i))
        for i in range(1, 8)
    ]
    db.add_all(trades)
    db.commit()

    summary = _flag(db)

    assert summary.cluster == 0


def test_cluster_below_min_trades_not_flagged(db):
    # Token 1: only 5 trades between 2 wallets (below min_trades=6)
    trades = [
        _sale(1, "0xaaa", "0xbbb", 1.0, T0 + timedelta(hours=i), str(i))
        for i in range(5)
    ]
    db.add_all(trades)
    db.commit()

    summary = _flag(db)

    assert summary.cluster == 0


def test_cluster_outside_window_not_flagged(db):
    # 7 trades between 2 wallets, but all happened before the 30-day window.
    # We anchor _cluster_ref_time so that T0 is 31 days before the window start.
    ref_time = T0 + timedelta(days=31)
    trades = [
        _sale(1, "0xaaa", "0xbbb", 1.0, T0 + timedelta(hours=i), str(i))
        for i in range(7)
    ]
    db.add_all(trades)
    db.commit()

    summary = flag_wash_trades(db, CONTRACT, _cluster_ref_time=ref_time)

    assert summary.cluster == 0


# ── Rule 4: price outlier (per-rarity-band, 8× median) ───────────────────────

def test_price_outlier_flagged(db):
    # No traits → all tokens in band 0 → collection-wide median = 1.0 ETH.
    # 9.0 ETH > 8× median → flagged.
    clean = [
        _sale(i, "0xaaa", "0xbbb", 1.0, T0 + timedelta(hours=i), str(i))
        for i in range(10)
    ]
    outlier = _sale(10, "0xaaa", "0xbbb", 9.0, T0 + timedelta(hours=10), "out")
    db.add_all(clean + [outlier])
    db.commit()

    summary = _flag(db)

    assert summary.price_outlier == 1
    db.refresh(outlier)
    assert outlier.wash_trade_flag is True
    for s in clean:
        db.refresh(s)
        assert s.wash_trade_flag is False


def test_price_outlier_at_exact_threshold_not_flagged(db):
    # 8.0 ETH = exactly 8× median — should NOT be flagged (> not >=)
    clean = [
        _sale(i, "0xaaa", "0xbbb", 1.0, T0 + timedelta(hours=i), str(i))
        for i in range(10)
    ]
    edge = _sale(10, "0xaaa", "0xbbb", 8.0, T0 + timedelta(hours=10), "edge")
    db.add_all(clean + [edge])
    db.commit()

    summary = _flag(db)

    assert summary.price_outlier == 0


# ── Summary totals ────────────────────────────────────────────────────────────

def test_summary_total_is_sum_of_rules(db):
    sale = _sale(1, "0xaaa", "0xaaa", 1.0)  # self-trade
    db.add(sale)
    db.commit()

    summary = _flag(db)

    assert summary.total == summary.self_trade + summary.round_trip + summary.cluster + summary.price_outlier


def test_already_flagged_rows_not_double_counted(db):
    # Pre-flag a sale; running detection again should not increment counts.
    sale = _sale(1, "0xaaa", "0xaaa", 1.0)
    sale.wash_trade_flag = True
    db.add(sale)
    db.commit()

    summary = _flag(db)

    assert summary.total == 0
