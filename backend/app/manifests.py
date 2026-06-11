"""Ranking manifest builder and writer."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from Crypto.Hash import keccak

if TYPE_CHECKING:
    from app.scoring.market_premium import MarketPremiumResult

OUTPUT_DIR = Path(__file__).parent.parent / "output"

W_STAT = 0.5
W_MARKET = 0.5


def _nan_none(v: object) -> float | None:
    """Return None if v is None or NaN, else round to 6 dp."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


def build_ranking_manifest(
    contract_address: str,
    chain: str,
    total_supply: int,
    eligible_supply: int,
    snapshot_block: int | None,
    ranked_traits: list[dict],
    market_result: MarketPremiumResult | None = None,
) -> dict:
    """Build the Phase 1 ranking manifest dict.

    When *market_result* is provided the manifest is fully populated and
    combined_score blends stat_norm (50 %) + market_norm (50 %).
    """
    # Build a lookup: (category, value) → market row dict
    market_lookup: dict[tuple[str, str], dict] = {}
    if market_result is not None and not market_result.traits.empty:
        for _, row in market_result.traits.iterrows():
            key = (row["trait_category"], row["trait_value"])
            market_lookup[key] = row.to_dict()

    has_market = bool(market_lookup)
    w_stat = W_STAT if has_market else 1.0
    w_market = W_MARKET if has_market else 0.0

    trait_rankings = []
    for i, row in enumerate(ranked_traits):
        cat, val = row["trait_category"], row["trait_value"]
        m = market_lookup.get((cat, val))

        market_coef = _nan_none(m["market_coef"]) if m else None
        market_se = _nan_none(m["market_se"]) if m else None
        market_norm_val = _nan_none(m["market_norm"]) if m else None
        n_sales = int(m["n_sales"]) if m else None
        low_conf = bool(m["low_confidence"]) if m else None

        stat_n = float(row["stat_norm"])
        if has_market and market_norm_val is not None:
            combined = round(w_stat * stat_n + w_market * market_norm_val, 6)
        else:
            combined = round(stat_n, 6)

        trait_rankings.append({
            "rank": i + 1,
            "trait_category": cat,
            "trait_value": val,
            "token_count": int(row["token_count"]),
            "frequency": round(float(row["frequency"]), 6),
            "stat_norm": round(stat_n, 6),
            "market_premium": market_coef,
            "market_premium_se": market_se,
            "market_norm": market_norm_val,
            "n_sales": n_sales,
            "low_confidence": low_conf,
            "combined_score": combined,
            "pinned": False,
        })

    # Re-rank by combined_score descending.
    trait_rankings.sort(key=lambda r: r["combined_score"], reverse=True)
    for i, r in enumerate(trait_rankings):
        r["rank"] = i + 1

    regression_meta = None
    if market_result is not None:
        regression_meta = {
            "method": market_result.method,
            "r_squared": _nan_none(market_result.r_squared),
            "n_obs": market_result.n_obs,
        }

    return {
        "manifest_id": str(uuid.uuid4()),
        "schema_version": "1.0",
        "collection": {
            "contract_address": contract_address,
            "chain": chain,
            "total_supply": total_supply,
            "eligible_supply": eligible_supply,
        },
        "snapshot": {
            "block_number": snapshot_block,
            "block_timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "weights": {"w_stat": w_stat, "w_market": w_market},
        "regression": regression_meta,
        "trait_rankings": trait_rankings,
        "approval": None,
    }


def write_ranking_manifest(contract_address: str, manifest: dict) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{contract_address}_ranking_manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    return path


def compute_manifest_hash(manifest: dict) -> str:
    """keccak256 over canonical JSON with `approval` nulled, so the hash commits
    to the rules being approved (and is reproducible from the published manifest)."""
    canonical = {**manifest, "approval": None}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = keccak.new(data=encoded, digest_bits=256).digest()
    return "0x" + digest.hex()
