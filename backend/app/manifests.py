"""Ranking manifest builder and writer."""

from __future__ import annotations

import json
import math
import os
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
    w_stat: float = W_STAT,
    w_market: float = W_MARKET,
) -> dict:
    """Build the Phase 1 ranking manifest dict.

    *w_stat* / *w_market* are the declared stat-vs-market blend (default 50/50)
    and are always recorded in ``manifest["weights"]``, even when no market data
    exists. ``combined_score`` blends ``w_stat * stat_norm + w_market *
    market_norm`` for any trait that has a market_norm, and falls back to
    ``stat_norm`` alone for traits without one — so a missing market signal drops
    the market term for that trait rather than silently reweighting the rest.
    The approve endpoint re-runs this blend with the approver's chosen weights.
    """
    # Build a lookup: (category, value) → market row dict
    market_lookup: dict[tuple[str, str], dict] = {}
    if market_result is not None and not market_result.traits.empty:
        for _, row in market_result.traits.iterrows():
            key = (row["trait_category"], row["trait_value"])
            market_lookup[key] = row.to_dict()

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
        if market_norm_val is not None:
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


def blend_combined_score(
    stat_norm: float | None,
    market_norm: float | None,
    w_stat: float,
    w_market: float,
) -> float | None:
    """Re-blend one trait's combined_score with the given weights.

    Mirrors build_ranking_manifest: blend stat + market when market_norm is
    present, else stat_norm alone. Used by the approve endpoint to apply the
    approver's chosen weights to an already-scored manifest.
    """
    if stat_norm is None:
        return None
    if market_norm is not None:
        return round(w_stat * float(stat_norm) + w_market * float(market_norm), 6)
    return round(float(stat_norm), 6)


def atomic_write_json(path: Path, manifest: dict) -> None:
    """Write a manifest so readers never see a torn file.

    Serializes to a uniquely-named temp file in the target directory, then
    os.replace()s it onto *path* — atomic on POSIX and Windows (same volume).
    A crash mid-write leaves the old manifest intact; concurrent writers
    degrade to clean last-writer-wins instead of interleaved JSON.
    """
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(manifest, indent=2))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_ranking_manifest(contract_address: str, manifest: dict) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{contract_address}_ranking_manifest.json"
    atomic_write_json(path, manifest)
    return path


def write_atlas_manifest(contract_address: str, manifest: dict) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{contract_address}_atlas_manifest.json"
    atomic_write_json(path, manifest)
    return path


def atlas_manifest_path(contract_address: str) -> Path:
    return OUTPUT_DIR / f"{contract_address.lower()}_atlas_manifest.json"


def load_atlas_manifest(contract_address: str) -> dict | None:
    """Read a generated atlas manifest, or None if it hasn't been generated yet."""
    path = atlas_manifest_path(contract_address)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _canonical_number(value: int | float) -> str:
    """Language-neutral decimal string for a JSON number (PMCH v1).

    The rule is defined on the *value*, not the Python type, so any language can
    reproduce it from the published JSON (where int/float is indistinguishable):

      * integer-valued (incl. ``1.0``, ``-0.0``) → plain decimal integer string
        (``"1000"``, ``"0"``); never scientific (manifest ints are < 1e15).
      * otherwise → fixed 6-fraction-digit decimal (``"0.500000"``). Inputs MUST
        already be rounded to ≤6 dp (every manifest producer does), so this only
        zero-pads — no rounding decision is taken, which is what keeps Python
        ``%.6f`` and JS ``toFixed(6)`` byte-identical.

    NaN/Infinity are rejected (they have no canonical decimal form).
    """
    if isinstance(value, bool):  # bool is an int subclass; should never reach here
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return str(value)
    f = float(value)
    if not math.isfinite(f):
        raise ValueError(f"non-finite number is not canonicalizable: {value!r}")
    if f.is_integer():
        return str(int(f))
    s = f"{f:.6f}"
    return "0.000000" if s == "-0.000000" else s


def canonical_serialize(value: object) -> str:
    """Deterministic, language-neutral string form of a JSON value (PMCH v1).

    Spec: objects emit keys sorted by Unicode code point as ``{"k":v,...}`` with
    no whitespace; arrays preserve order; strings use JSON escaping with non-ASCII
    left literal (matches Python ``json.dumps(ensure_ascii=False)`` and JS
    ``JSON.stringify``); numbers use :func:`_canonical_number`; ``true``/``false``/
    ``null`` as-is. The result is hashed as UTF-8. Keep this byte-for-byte in
    lockstep with ``frontend/src/lib/canonicalHash.ts``.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _canonical_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(canonical_serialize(v) for v in value) + "]"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0])
        return (
            "{"
            + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonical_serialize(v) for k, v in items)
            + "}"
        )
    raise TypeError(f"cannot canonicalize value of type {type(value).__name__}")


def compute_manifest_hash(manifest: dict) -> str:
    """keccak256 over the PMCH-v1 canonical form with `approval` nulled, so the
    hash commits to the rules being approved and is reproducibly verifiable from
    the published manifest in any language (see :func:`canonical_serialize`)."""
    canonical = {**manifest, "approval": None}
    encoded = canonical_serialize(canonical).encode("utf-8")
    digest = keccak.new(data=encoded, digest_bits=256).digest()
    return "0x" + digest.hex()
