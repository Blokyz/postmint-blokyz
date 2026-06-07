"""Unit tests for market premium regression.

Uses the live test DB (PostgreSQL) via the `db` fixture in conftest.py.
Each test inserts its own Sales + Traits rows and verifies the regression output.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.db.models import Sale, Trait
from app.scoring.market_premium import MIN_SALES, MIN_TRAIT_SALES, compute_market_premium

CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d"
T0 = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── helpers ───────────────────────────────────────────────────────────────────

def _sale(token_id: int, price: float, index: int) -> Sale:
    return Sale(
        contract_address=CONTRACT,
        token_id=token_id,
        sale_price_eth=price,
        seller_address="0xseller",
        buyer_address="0xbuyer",
        sold_at=T0 + timedelta(hours=index),
        tx_hash=f"0x{'00' * 30}{index:04d}",
    )


def _trait(token_id: int, category: str, value: str) -> Trait:
    return Trait(
        contract_address=CONTRACT,
        token_id=token_id,
        trait_category=category,
        trait_value=value,
    )


def _insert_collection(db, n_per_group: int, bg_premium: float, eyes_premium: float):
    """Insert n_per_group sales × 4 trait combinations.

    Background:  "Blue" (baseline 0)  vs  "Red" (+bg_premium)
    Eyes:        "Normal" (baseline 0) vs  "Laser" (+eyes_premium)
    Prices are log-additive: price = exp(1 + bg + eyes + tiny_noise).
    Returns total number of sales inserted.
    """
    idx = 0
    token_id = 1
    for bg, bg_p in [("Blue", 0.0), ("Red", bg_premium)]:
        for eyes, eyes_p in [("Normal", 0.0), ("Laser", eyes_premium)]:
            for j in range(n_per_group):
                noise = 0.001 * j
                price = np.exp(1.0 + bg_p + eyes_p + noise)
                sale = _sale(token_id, price, idx)
                db.add(sale)
                db.add(_trait(token_id, "Background", bg))
                db.add(_trait(token_id, "Eyes", eyes))
                token_id += 1
                idx += 1
    db.commit()
    return idx  # total sales


# ── directional coefficient tests ────────────────────────────────────────────

def test_high_price_trait_gets_positive_coef(db):
    """Traits correlated with higher prices should have larger market_coef."""
    _insert_collection(db, n_per_group=12, bg_premium=0.5, eyes_premium=1.5)

    result = compute_market_premium(db, CONTRACT)

    assert result.method in ("ols", "ridge")
    traits = result.traits.set_index(["trait_category", "trait_value"])

    red_coef = traits.loc[("Background", "Red"), "market_coef"]
    blue_coef = traits.loc[("Background", "Blue"), "market_coef"]
    laser_coef = traits.loc[("Eyes", "Laser"), "market_coef"]
    normal_coef = traits.loc[("Eyes", "Normal"), "market_coef"]

    assert red_coef > blue_coef, "Red background should command a premium over Blue"
    assert laser_coef > normal_coef, "Laser eyes should command a premium over Normal"
    # Stronger price signal → larger gap
    assert (laser_coef - normal_coef) > (red_coef - blue_coef)


def test_market_norm_range(db):
    """market_norm must be in [0, 1] for every trait."""
    _insert_collection(db, n_per_group=12, bg_premium=0.3, eyes_premium=1.0)

    result = compute_market_premium(db, CONTRACT)

    assert not result.traits.empty
    norms = result.traits["market_norm"]
    assert norms.min() >= 0.0 - 1e-9
    assert norms.max() <= 1.0 + 1e-9


def test_all_traits_present_in_output(db):
    """Every (category, value) pair that appears in traits must appear in the result."""
    _insert_collection(db, n_per_group=10, bg_premium=0.4, eyes_premium=1.2)

    result = compute_market_premium(db, CONTRACT)

    keys = set(zip(result.traits["trait_category"], result.traits["trait_value"]))
    assert ("Background", "Blue") in keys
    assert ("Background", "Red") in keys
    assert ("Eyes", "Normal") in keys
    assert ("Eyes", "Laser") in keys


# ── OLS-specific tests ────────────────────────────────────────────────────────

def test_ols_selected_when_n_obs_much_greater_than_features(db):
    """With 4 trait dummies and 48 observations OLS should be chosen."""
    _insert_collection(db, n_per_group=12, bg_premium=0.5, eyes_premium=1.5)

    result = compute_market_premium(db, CONTRACT)

    assert result.method == "ols"


def test_ols_provides_se_and_pval(db):
    """OLS path must populate market_se and market_pval for non-reference traits."""
    _insert_collection(db, n_per_group=12, bg_premium=0.5, eyes_premium=1.5)

    result = compute_market_premium(db, CONTRACT)
    assert result.method == "ols"

    # Some traits will have SE / p-val (non-reference ones).
    non_ref = result.traits.dropna(subset=["market_se", "market_pval"])
    assert len(non_ref) > 0
    assert (non_ref["market_se"] > 0).all()
    assert ((non_ref["market_pval"] >= 0) & (non_ref["market_pval"] <= 1)).all()


def test_r_squared_is_positive(db):
    """Strong price signal → R² should be > 0."""
    _insert_collection(db, n_per_group=12, bg_premium=0.5, eyes_premium=1.5)

    result = compute_market_premium(db, CONTRACT)

    assert result.r_squared is not None
    assert result.r_squared > 0.0


# ── Ridge fallback tests ──────────────────────────────────────────────────────

def _insert_sparse_collection(db, n_sales: int):
    """Insert n_sales sales where every sale/token has a unique trait combination,
    giving n_features ≈ n_sales, forcing Ridge (n_obs ≤ 2 × n_features).
    """
    # 2 categories × n_sales unique values each → 2*n_sales features, n_obs=n_sales.
    for i in range(n_sales):
        price = np.exp(1.0 + 0.1 * (i % 5))
        sale = _sale(i + 1, price, i)
        db.add(sale)
        db.add(_trait(i + 1, "Cat_A", f"val_{i}"))
        db.add(_trait(i + 1, "Cat_B", f"val_{i}"))
    db.commit()


def test_ridge_fallback_when_underdetermined(db):
    """When n_features > n_obs / 2, Ridge should be selected."""
    _insert_sparse_collection(db, n_sales=MIN_SALES)

    result = compute_market_premium(db, CONTRACT)

    assert result.method == "ridge"


def test_ridge_se_and_pval_are_none(db):
    """Ridge results must not have SE or p-values (they're not valid for Ridge)."""
    _insert_sparse_collection(db, n_sales=MIN_SALES)

    result = compute_market_premium(db, CONTRACT)
    assert result.method == "ridge"

    # All SE and p-val must be None/NaN — no valid statistical inference.
    import math
    for _, row in result.traits.iterrows():
        assert row["market_se"] is None or (
            isinstance(row["market_se"], float) and math.isnan(row["market_se"])
        )
        assert row["market_pval"] is None or (
            isinstance(row["market_pval"], float) and math.isnan(row["market_pval"])
        )


# ── Insufficient data tests ───────────────────────────────────────────────────

def test_insufficient_sales_returns_none_method(db):
    """Fewer than MIN_SALES clean sales → method='none', empty traits."""
    for i in range(MIN_SALES - 1):
        price = np.exp(1.0 + 0.01 * i)
        db.add(_sale(i + 1, price, i))
        db.add(_trait(i + 1, "Background", "Blue"))
    db.commit()

    result = compute_market_premium(db, CONTRACT)

    assert result.method == "none"
    assert result.traits.empty
    assert result.n_obs == 0


def test_wash_trade_sales_excluded(db):
    """Wash-flagged sales must not be counted toward MIN_SALES or affect coefficients."""
    # Insert MIN_SALES - 1 clean sales + 10 wash-trade sales → still insufficient.
    for i in range(MIN_SALES - 1):
        db.add(_sale(i + 1, np.exp(1.0), i))
        db.add(_trait(i + 1, "Background", "Blue"))
    for i in range(10):
        wash_sale = _sale(1000 + i, 99.0, 1000 + i)
        wash_sale.wash_trade_flag = True
        db.add(wash_sale)
        db.add(_trait(1000 + i, "Background", "Red"))
    db.commit()

    result = compute_market_premium(db, CONTRACT)

    assert result.method == "none"


# ── Low-confidence flag ───────────────────────────────────────────────────────

def test_low_confidence_flag_for_rare_trait(db):
    """A trait that appears in fewer than MIN_TRAIT_SALES sales gets low_confidence=True."""
    # 30 clean sales for (Blue, Normal) — well above threshold.
    for i in range(30):
        db.add(_sale(i + 1, np.exp(1.0 + 0.001 * i), i))
        db.add(_trait(i + 1, "Background", "Blue"))
        db.add(_trait(i + 1, "Eyes", "Normal"))
    # Only 2 sales for (Background, Red) — below MIN_TRAIT_SALES.
    for i in range(MIN_TRAIT_SALES - 1):
        db.add(_sale(100 + i, np.exp(1.5), 100 + i))
        db.add(_trait(100 + i, "Background", "Red"))
        db.add(_trait(100 + i, "Eyes", "Normal"))
    db.commit()

    result = compute_market_premium(db, CONTRACT)

    assert result.method != "none"
    traits = result.traits.set_index(["trait_category", "trait_value"])
    assert traits.loc[("Background", "Red"), "low_confidence"] == True
    assert traits.loc[("Background", "Blue"), "low_confidence"] == False


# ── n_obs reported correctly ──────────────────────────────────────────────────

def test_n_obs_matches_clean_sale_count(db):
    """n_obs in the result should equal the number of non-wash-trade sales with traits."""
    n = 36
    _insert_collection(db, n_per_group=n // 4, bg_premium=0.4, eyes_premium=1.0)

    result = compute_market_premium(db, CONTRACT)

    assert result.n_obs == n
