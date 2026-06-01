import json
from pathlib import Path

import pytest

from app.manifests import build_ranking_manifest, write_ranking_manifest

_CONTRACT = "0xdeadbeef00000000000000000000000000000001"
_TRAITS = [
    {
        "trait_category": "Fur",
        "trait_value": "Gold",
        "token_count": 1,
        "frequency": 0.0001,
        "stat_norm": 1.0,
    },
    {
        "trait_category": "Fur",
        "trait_value": "Brown",
        "token_count": 1370,
        "frequency": 0.137,
        "stat_norm": 0.0,
    },
]


def _build(**overrides):
    defaults = dict(
        contract_address=_CONTRACT,
        chain="ethereum",
        total_supply=10000,
        eligible_supply=9988,
        snapshot_block=21_500_000,
        ranked_traits=_TRAITS,
    )
    return build_ranking_manifest(**{**defaults, **overrides})


# ── Structure ──────────────────────────────────────────────────────────────────

def test_schema_version():
    assert _build()["schema_version"] == "1.0"


def test_collection_fields():
    m = _build()
    assert m["collection"]["contract_address"] == _CONTRACT
    assert m["collection"]["chain"] == "ethereum"
    assert m["collection"]["total_supply"] == 10000
    assert m["collection"]["eligible_supply"] == 9988


def test_snapshot_block():
    assert _build()["snapshot"]["block_number"] == 21_500_000


def test_snapshot_block_none():
    assert _build(snapshot_block=None)["snapshot"]["block_number"] is None


def test_default_weights():
    m = _build()
    assert m["weights"] == {"w_stat": 0.5, "w_market": 0.5}


def test_regression_is_null_before_scoring():
    assert _build()["regression"] is None


def test_approval_is_null_before_approval():
    assert _build()["approval"] is None


# ── Trait rankings ─────────────────────────────────────────────────────────────

def test_trait_count():
    assert len(_build()["trait_rankings"]) == 2


def test_ranks_are_sequential_from_1():
    ranks = [t["rank"] for t in _build()["trait_rankings"]]
    assert ranks == [1, 2]


def test_market_fields_are_null():
    for t in _build()["trait_rankings"]:
        assert t["market_premium"] is None
        assert t["market_norm"] is None
        assert t["market_premium_se"] is None
        assert t["low_confidence"] is None
        assert t["n_sales"] is None


def test_combined_score_equals_stat_norm_before_regression():
    for t in _build()["trait_rankings"]:
        assert t["combined_score"] == pytest.approx(t["stat_norm"])


def test_pinned_defaults_false():
    for t in _build()["trait_rankings"]:
        assert t["pinned"] is False


def test_frequency_rounded():
    m = _build()
    # Frequency stored to 6 decimal places
    for t in m["trait_rankings"]:
        assert isinstance(t["frequency"], float)


def test_empty_traits():
    m = _build(ranked_traits=[])
    assert m["trait_rankings"] == []


# ── Identity ───────────────────────────────────────────────────────────────────

def test_manifest_id_is_unique_per_call():
    assert _build()["manifest_id"] != _build()["manifest_id"]


# ── Writer ─────────────────────────────────────────────────────────────────────

def test_write_ranking_manifest_creates_file(tmp_path, monkeypatch):
    import app.manifests as manifests_mod
    monkeypatch.setattr(manifests_mod, "OUTPUT_DIR", tmp_path)

    m = _build()
    path = write_ranking_manifest(_CONTRACT, m)

    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert on_disk["manifest_id"] == m["manifest_id"]


def test_write_ranking_manifest_filename(tmp_path, monkeypatch):
    import app.manifests as manifests_mod
    monkeypatch.setattr(manifests_mod, "OUTPUT_DIR", tmp_path)

    path = write_ranking_manifest(_CONTRACT, _build())
    assert path.name == f"{_CONTRACT}_ranking_manifest.json"
