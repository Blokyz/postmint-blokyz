"""OLS / Ridge regression to estimate per-trait market premium from clean sales data.

Fits log(sale_price_eth) ~ trait_dummies on non-wash-trade sales.
Auto-selects OLS (statsmodels, gives SEs + p-values) when the design matrix is
well-conditioned; falls back to Ridge (sklearn RidgeCV) otherwise.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_SALES = 30          # minimum clean sales required to fit any model
MIN_TRAIT_SALES = 5     # below this → low_confidence = True for that trait
ILL_COND_THRESHOLD = 1e12
RIDGE_ALPHAS = (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)


@dataclass
class MarketPremiumResult:
    traits: pd.DataFrame          # see _TRAIT_COLS below
    method: str                   # "ols", "ridge", or "none"
    r_squared: float | None
    n_obs: int


_TRAIT_COLS = [
    "trait_category", "trait_value",
    "market_coef", "market_se", "market_pval",
    "n_sales", "market_norm", "low_confidence",
]

_EMPTY = MarketPremiumResult(
    traits=pd.DataFrame(columns=_TRAIT_COLS),
    method="none",
    r_squared=None,
    n_obs=0,
)


def compute_market_premium(db: Session, contract: str) -> MarketPremiumResult:
    """Return per-trait market premium coefficients for *contract*.

    Uses only sales with wash_trade_flag=False and sale_price_eth > 0.
    Returns _EMPTY when there are fewer than MIN_SALES qualifying sales.
    """
    rows = db.execute(
        text("""
            SELECT s.id              AS sale_id,
                   s.token_id,
                   CAST(s.sale_price_eth AS double precision) AS sale_price_eth,
                   t.trait_category,
                   t.trait_value
            FROM   sales  s
            JOIN   traits t
              ON   t.contract_address = s.contract_address
             AND   t.token_id         = s.token_id
            WHERE  s.contract_address = :contract
              AND  NOT s.wash_trade_flag
              AND  s.sale_price_eth   > 0
        """),
        {"contract": contract},
    ).fetchall()

    if not rows:
        return _EMPTY

    df = pd.DataFrame(rows, columns=["sale_id", "token_id", "sale_price_eth",
                                     "trait_category", "trait_value"])

    # Count unique sales that include each (category, value) pair.
    trait_sale_counts = (
        df.groupby(["trait_category", "trait_value"])["sale_id"]
        .nunique()
        .reset_index(name="n_sales")
    )

    # One row per sale.
    sale_prices = df[["sale_id", "sale_price_eth"]].drop_duplicates("sale_id")
    n_obs = len(sale_prices)

    if n_obs < MIN_SALES:
        return _EMPTY

    y = np.log(sale_prices["sale_price_eth"].values.astype(float))

    # Build design matrix: rows = sales, cols = (trait_category, trait_value) pairs.
    pivot = (
        df[["sale_id", "trait_category", "trait_value"]]
        .assign(present=1)
        .pivot_table(
            index="sale_id",
            columns=["trait_category", "trait_value"],
            values="present",
            aggfunc="max",
            fill_value=0,
        )
    )
    pivot = pivot.reindex(sale_prices["sale_id"].values, fill_value=0)

    all_keys: list[tuple[str, str]] = list(pivot.columns)  # MultiIndex → list of (cat, val)
    X = pivot.values.astype(float)

    # Pre-compute the reference-level-dropped column indices for OLS evaluation.
    # The full X is always ill-conditioned (within-category columns sum to 1),
    # so condition number must be checked on the reduced matrix.
    seen_cats: set[str] = set()
    kept_idx = []
    for i, (cat, _val) in enumerate(all_keys):
        if cat in seen_cats:
            kept_idx.append(i)
        else:
            seen_cats.add(cat)   # first value per category = reference level, skip

    X_reduced = X[:, kept_idx]
    n_features_reduced = X_reduced.shape[1]

    # Method selection.
    if n_features_reduced == 0 or n_obs <= 2 * n_features_reduced:
        use_ridge = True
    else:
        use_ridge = np.linalg.cond(X_reduced) > ILL_COND_THRESHOLD

    if use_ridge:
        fit = _fit_ridge(X, y, all_keys)
    else:
        fit = _fit_ols(X, y, all_keys)
        if fit is None:
            fit = _fit_ridge(X, y, all_keys)

    if fit is None:
        return _EMPTY

    coef_df, method, r_squared = fit

    # OLS drops one reference level per category; add them back with coef = 0.
    fitted_keys = set(coef_df["trait_key"])
    missing = [k for k in all_keys if k not in fitted_keys]
    if missing:
        ref_df = pd.DataFrame({
            "trait_key": missing,
            "market_coef": 0.0,
            "market_se": float("nan"),
            "market_pval": float("nan"),
        })
        coef_df = pd.concat([coef_df, ref_df], ignore_index=True)

    # Normalize to [0, 1].
    c_min, c_max = coef_df["market_coef"].min(), coef_df["market_coef"].max()
    if c_max > c_min:
        coef_df["market_norm"] = (coef_df["market_coef"] - c_min) / (c_max - c_min)
    else:
        coef_df["market_norm"] = 0.5

    # Unpack (category, value) tuples.
    coef_df["trait_category"] = [k[0] for k in coef_df["trait_key"]]
    coef_df["trait_value"] = [k[1] for k in coef_df["trait_key"]]

    # Merge n_sales and flag low-confidence traits.
    coef_df = coef_df.merge(trait_sale_counts, on=["trait_category", "trait_value"], how="left")
    coef_df["n_sales"] = coef_df["n_sales"].fillna(0).astype(int)
    coef_df["low_confidence"] = coef_df["n_sales"] < MIN_TRAIT_SALES

    return MarketPremiumResult(
        traits=coef_df[_TRAIT_COLS].reset_index(drop=True),
        method=method,
        r_squared=r_squared,
        n_obs=n_obs,
    )


# ── private helpers ───────────────────────────────────────────────────────────

log = logging.getLogger(__name__)


def _fit_ols(
    X: np.ndarray,
    y: np.ndarray,
    all_keys: list[tuple[str, str]],
) -> tuple[pd.DataFrame, str, float] | None:
    """Fit OLS via statsmodels; drops first value per category as reference level."""
    try:
        import statsmodels.api as sm  # noqa: PLC0415

        # Identify reference levels: first (alphabetically ordered) value per category.
        seen: set[str] = set()
        keep: list[bool] = []
        for cat, _val in all_keys:
            if cat in seen:
                keep.append(True)
            else:
                seen.add(cat)
                keep.append(False)  # reference → dropped

        kept_idx = [i for i, k in enumerate(keep) if k]
        kept_keys = [all_keys[i] for i in kept_idx]

        X_ols = np.asfortranarray(X[:, kept_idx])
        X_const = sm.add_constant(X_ols, has_constant="add")

        model = sm.OLS(y, X_const).fit()

        coef_df = pd.DataFrame({
            "trait_key": kept_keys,
            "market_coef": model.params[1:],   # skip intercept
            "market_se": model.bse[1:],
            "market_pval": model.pvalues[1:],
        })
        return coef_df, "ols", float(model.rsquared)
    except Exception:
        log.warning("OLS fit failed, will try Ridge", exc_info=True)
        return None


def _fit_ridge(
    X: np.ndarray,
    y: np.ndarray,
    all_keys: list[tuple[str, str]],
) -> tuple[pd.DataFrame, str, float] | None:
    """Fit Ridge with cross-validated alpha via sklearn."""
    try:
        from sklearn.linear_model import RidgeCV  # noqa: PLC0415

        model = RidgeCV(alphas=RIDGE_ALPHAS, fit_intercept=True)
        model.fit(X, y)

        coef_df = pd.DataFrame({
            "trait_key": all_keys,
            "market_coef": model.coef_,
            "market_se": float("nan"),
            "market_pval": float("nan"),
        })
        return coef_df, "ridge", float(model.score(X, y))
    except Exception:
        log.warning("Ridge fit failed", exc_info=True)
        return None
