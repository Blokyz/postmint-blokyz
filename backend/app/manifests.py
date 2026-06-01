"""Ranking manifest builder and writer."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def build_ranking_manifest(
    contract_address: str,
    chain: str,
    total_supply: int,
    eligible_supply: int,
    snapshot_block: int | None,
    ranked_traits: list[dict],
) -> dict:
    """Build the Phase 1 ranking manifest dict.

    market_premium fields are None until Sprint 2 (OLS regression).
    combined_score = stat_norm only at this stage.
    """
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
        "weights": {"w_stat": 0.5, "w_market": 0.5},
        "regression": None,
        "trait_rankings": [
            {
                "rank": i + 1,
                "trait_category": row["trait_category"],
                "trait_value": row["trait_value"],
                "token_count": int(row["token_count"]),
                "frequency": round(float(row["frequency"]), 6),
                "stat_norm": round(float(row["stat_norm"]), 6),
                "market_premium": None,
                "market_premium_se": None,
                "market_norm": None,
                "n_sales": None,
                "low_confidence": None,
                "combined_score": round(float(row["stat_norm"]), 6),
                "pinned": False,
            }
            for i, row in enumerate(ranked_traits)
        ],
        "approval": None,
    }


def write_ranking_manifest(contract_address: str, manifest: dict) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{contract_address}_ranking_manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    return path
