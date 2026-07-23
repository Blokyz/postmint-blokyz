"""Canonical manifest-hash spec (PMCH v1) — no DB required.

Two layers: (1) hand-reasoned semantic goldens that pin the spec's behavior, and
(2) a self-check against the shared fixture that the JS reference also verifies
(frontend/scripts/canonical-hash-check.mjs), proving cross-language equivalence.
"""

import json
import math
from pathlib import Path

import pytest

from app.manifests import canonical_serialize, compute_manifest_hash

_FIXTURE = Path(__file__).parent / "fixtures" / "canonical_hash_vectors.json"


# ── Semantic goldens (the spec, by hand) ─────────────────────────────────────

def test_keys_sorted_independent_of_insertion_order():
    assert canonical_serialize({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert canonical_serialize({"a": 1, "b": 2}) == canonical_serialize({"b": 2, "a": 1})


def test_int_and_whole_float_collapse():
    # Reproducible from published JSON: 1000 and 1000.0 are indistinguishable.
    assert canonical_serialize(1000) == "1000"
    assert canonical_serialize(1000.0) == "1000"
    assert canonical_serialize(-0.0) == "0"
    assert canonical_serialize(0) == "0"


def test_fractional_fixed_six_dp():
    assert canonical_serialize(0.5) == "0.500000"
    assert canonical_serialize(0.1) == "0.100000"
    assert canonical_serialize(0.123456) == "0.123456"


def test_whole_number_weights_collapse_to_integer():
    assert canonical_serialize({"w_stat": 1.0, "w_market": 0.0}) == '{"w_market":0,"w_stat":1}'


def test_bools_and_null():
    assert canonical_serialize(True) == "true"
    assert canonical_serialize(False) == "false"
    assert canonical_serialize(None) == "null"


def test_unicode_left_literal():
    assert canonical_serialize({"trait": "Café ✦ 日本"}) == '{"trait":"Café ✦ 日本"}'


def test_nested_and_arrays_preserve_array_order_sort_object_keys():
    v = {"z": {"b": 1, "a": 2}, "a": [3, 2, 1]}
    assert canonical_serialize(v) == '{"a":[3,2,1],"z":{"a":2,"b":1}}'


def test_non_finite_rejected():
    with pytest.raises(ValueError):
        canonical_serialize(math.inf)
    with pytest.raises(ValueError):
        canonical_serialize(math.nan)


def test_unsupported_type_rejected():
    with pytest.raises(TypeError):
        canonical_serialize({1, 2, 3})  # set is not JSON


# ── compute_manifest_hash behavior ───────────────────────────────────────────

def test_hash_is_deterministic_and_0x_32_bytes():
    m = {"a": 1, "trait_rankings": [{"rank": 1, "v": 0.5}]}
    h = compute_manifest_hash(m)
    assert h.startswith("0x") and len(h) == 66
    assert compute_manifest_hash(dict(reversed(list(m.items())))) == h


def test_hash_ignores_approval_field():
    base = {"schema_version": "1.0", "trait_rankings": []}
    h_none = compute_manifest_hash({**base, "approval": None})
    h_filled = compute_manifest_hash({**base, "approval": {"approver_address": "0xabc", "x": 1}})
    h_missing = compute_manifest_hash(base)
    assert h_none == h_filled == h_missing


def test_hash_changes_when_rules_change():
    base = {"trait_rankings": [{"rank": 1, "trait_value": "Gold", "pinned": False}]}
    flipped = {"trait_rankings": [{"rank": 1, "trait_value": "Gold", "pinned": True}]}
    assert compute_manifest_hash(base) != compute_manifest_hash(flipped)


# ── Cross-language fixture self-check ─────────────────────────────────────────

def _fixture() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_fixture_exists():
    assert _FIXTURE.exists(), "run scratchpad/gen_vectors.py to regenerate the fixture"


@pytest.mark.parametrize("entry", _fixture()["serialize"], ids=lambda e: e["name"])
def test_serialize_vectors_match_fixture(entry):
    from Crypto.Hash import keccak

    canonical = canonical_serialize(entry["value"])
    assert canonical == entry["canonical"]
    digest = "0x" + keccak.new(data=canonical.encode("utf-8"), digest_bits=256).hexdigest()
    assert digest == entry["keccak"]


@pytest.mark.parametrize("entry", _fixture()["manifest"], ids=lambda e: e["name"])
def test_manifest_vectors_match_fixture(entry):
    assert compute_manifest_hash(entry["manifest"]) == entry["hash"]
