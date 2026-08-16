"""OpenSea v2 listings client for the tier gallery (shopping Level B, 2026-08-15).

Answers ONE question the DB can't: which qualifying tokens are for sale right
now, and at what price. Everything degrades to "no listings" — missing
OPENSEA_API_KEY, a chain OpenSea doesn't serve (it dropped all testnets with
OS2, so Base Sepolia collections never get listings), or any API error — and
the gallery still renders from the DB alone.

Free-tier keys allow ~600 reads/hour, so listing fetches are TTL-cached
per contract (LISTINGS_TTL_SECONDS) and collection slugs are cached forever
(immutable on OpenSea).
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.ttl_cache import TTLCache

logger = logging.getLogger(__name__)

OPENSEA_BASE = "https://api.opensea.io/api/v2"
LISTINGS_TTL_SECONDS = 60.0
_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0)

# Collection.chain values -> OpenSea chain identifiers. Anything unmapped
# (base-sepolia, synthetic test contracts, ...) means "OpenSea can't help".
_OS_CHAIN = {
    "eth": "ethereum",
    "ethereum": "ethereum",
    "base": "base",
    "polygon": "matic",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
}

_slug_cache: dict[str, str] = {}
_listings_cache = TTLCache()


def opensea_chain(chain: str) -> str | None:
    return _OS_CHAIN.get((chain or "").lower())


def asset_url(chain: str, contract: str, token_id: int) -> str | None:
    """Public OpenSea item page, or None when the chain isn't on OpenSea."""
    os_chain = opensea_chain(chain)
    if os_chain is None:
        return None
    return f"https://opensea.io/assets/{os_chain}/{contract.lower()}/{token_id}"


def _get(path: str, params: dict | None = None) -> dict | None:
    key = get_settings().opensea_api_key
    if not key:
        return None
    try:
        resp = httpx.get(
            f"{OPENSEA_BASE}{path}",
            params=params,
            headers={"X-API-KEY": key, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("OpenSea request %s failed: %s", path, exc)
        return None


def collection_slug(contract: str, chain: str) -> str | None:
    """OpenSea collection slug for a contract (cached forever — slugs are immutable)."""
    contract = contract.lower()
    if contract in _slug_cache:
        return _slug_cache[contract]
    os_chain = opensea_chain(chain)
    if os_chain is None:
        return None
    data = _get(f"/chain/{os_chain}/contract/{contract}")
    slug = (data or {}).get("collection")
    if slug:
        _slug_cache[contract] = slug
    return slug


def _parse_best_listings(data: dict) -> dict[int, float]:
    """{token_id: price_eth} from a best-listings response; malformed entries skipped."""
    out: dict[int, float] = {}
    for listing in data.get("listings") or []:
        try:
            offer = listing["protocol_data"]["parameters"]["offer"][0]
            token_id = int(offer["identifierOrCriteria"])
            current = listing["price"]["current"]
            price = int(current["value"]) / 10 ** int(current["decimals"])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if token_id not in out or price < out[token_id]:
            out[token_id] = price
    return out


def listed_prices(contract: str, chain: str) -> dict[int, float]:
    """Cheapest current listing per token id for a collection, TTL-cached.

    Empty dict = no listings available (unlisted collection, unsupported chain,
    missing key, or API failure) — callers can't distinguish and don't need to;
    the gallery's `listings_live` flag reports whether OpenSea was reachable.
    """
    contract = contract.lower()
    cached = _listings_cache.get(("listings", contract), LISTINGS_TTL_SECONDS)
    if cached is not None:
        return cached

    prices: dict[int, float] = {}
    slug = collection_slug(contract, chain)
    if slug:
        # ponytail: one 100-listing page — cheapest-first covers the gallery cap;
        # follow `next` cursors if deep pools ever need more coverage.
        data = _get(f"/listings/collection/{slug}/best", params={"limit": 100})
        if data:
            prices = _parse_best_listings(data)
    _listings_cache.set(("listings", contract), prices)
    return prices
