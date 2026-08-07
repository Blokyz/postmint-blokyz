"""DB-free tests for the in-process rollup cache (app.ttl_cache)."""

import app.ttl_cache as ttl_cache_mod
from app.ttl_cache import TTLCache, contract_keys


def test_get_miss_returns_none():
    cache = TTLCache()
    assert cache.get(("standings", "0xabc"), ttl=30) is None


def test_set_then_get_hit():
    cache = TTLCache()
    cache.set(("standings", "0xabc"), {"tiers": []})
    assert cache.get(("standings", "0xabc"), ttl=30) == {"tiers": []}


def test_zero_ttl_disables_reads():
    cache = TTLCache()
    cache.set("k", "v")
    assert cache.get("k", ttl=0) is None
    assert cache.get("k", ttl=-1) is None


def test_expiry(monkeypatch):
    cache = TTLCache()
    t = [1000.0]
    monkeypatch.setattr(ttl_cache_mod.time, "monotonic", lambda: t[0])
    cache.set("k", "v")
    t[0] = 1029.0
    assert cache.get("k", ttl=30) == "v"
    t[0] = 1031.0
    assert cache.get("k", ttl=30) is None
    # Expired entry is evicted, not just hidden.
    assert "k" not in cache._store


def test_invalidate_and_clear():
    cache = TTLCache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.invalidate("a", "missing")
    assert cache.get("a", ttl=30) is None
    assert cache.get("b", ttl=30) == 2
    cache.clear()
    assert cache.get("b", ttl=30) is None


def test_contract_keys_lowercase_both_surfaces():
    assert contract_keys("0xABC") == (("standings", "0xabc"), ("summary", "0xabc"))
