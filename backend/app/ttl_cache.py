"""Tiny in-process TTL cache for hot read rollups (standings + directory summaries).

The Paddock directory recomputes a claims rollup per collection per request and
`/standings` re-aggregates on every poll, so both are fronted by this cache
(`Settings.standings_cache_ttl_seconds`, default 30s; 0 disables — the test
suite runs with it disabled so seeded rows are always visible immediately).

Claim mutations (`/claim/confirm`) invalidate their contract's entries so a
holder sees their win reflected instantly; background transfer-poller ownership
updates ride out the TTL. In-process only — with multiple API workers each holds
its own copy, which is fine for a staleness-bounded rollup.
"""

from __future__ import annotations

import time
from typing import Any, Hashable


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[Hashable, tuple[Any, float]] = {}

    def get(self, key: Hashable, ttl: float) -> Any | None:
        """Value for `key` if stored within the last `ttl` seconds, else None.
        A non-positive ttl disables reads entirely."""
        if ttl <= 0:
            return None
        hit = self._store.get(key)
        if hit is None:
            return None
        value, stored_at = hit
        if time.monotonic() - stored_at > ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Hashable, value: Any) -> None:
        self._store[key] = (value, time.monotonic())

    def invalidate(self, *keys: Hashable) -> None:
        for key in keys:
            self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


# Shared instance for the race/directory rollups.
race_cache = TTLCache()


def contract_keys(contract: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """Both cache keys a claim mutation on `contract` must invalidate."""
    c = contract.lower()
    return ("standings", c), ("summary", c)
