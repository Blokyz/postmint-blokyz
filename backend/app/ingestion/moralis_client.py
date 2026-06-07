"""Moralis NFT API v2.2 client — paginated token + trait fetcher."""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from httpx import HTTPStatusError, TransportError

from app.ingestion.errors import MoralisApiError

MORALIS_BASE = "https://deep-index.moralis.io/api/v2.2"
PAGE_SIZE = 100
RATE_SLEEP = 0.025  # 40 req/s free tier

# Accept common user-facing chain names and map to Moralis identifiers.
_CHAIN_MAP: dict[str, str] = {
    "ethereum": "eth",
    "eth": "eth",
    "polygon": "polygon",
    "base": "base",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
}


def _normalize_chain(chain: str) -> str:
    return _CHAIN_MAP.get(chain.lower(), chain.lower())


def _normalize_value(raw: object) -> str:
    s = str(raw).strip() if raw is not None else ""
    return "None" if s.lower() in {"none", "null", "n/a", ""} else s


def _raise_if_empty_collection(
    contract: str,
    chain: str,
    data: dict,
    api_key: str,
) -> None:
    """Moralis often returns HTTP 200 with an empty result when NFT API access is missing."""
    if data.get("result"):
        return

    msg = data.get("message")
    if msg:
        raise MoralisApiError(f"Moralis error for {contract} on {chain}: {msg}")

    # Cross-check collection stats — empty here means the key cannot read this collection.
    try:
        stats_resp = httpx.get(
            f"{MORALIS_BASE}/nft/{contract}/stats",
            params={"chain": _normalize_chain(chain)},
            headers={"X-API-Key": api_key},
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
        )
        stats_resp.raise_for_status()
        stats = stats_resp.json()
        total = stats.get("total_tokens")
        if total not in (None, "0", 0):
            raise MoralisApiError(
                f"Moralis returned 0 NFTs on page 1 but reports total_tokens={total} "
                f"for {contract} on {chain}. Retry in a few minutes."
            )
    except HTTPStatusError as exc:
        raise MoralisApiError(
            f"Moralis NFT stats unavailable for {contract} on {chain}: HTTP {exc.response.status_code}"
        ) from exc
    except TransportError as exc:
        raise MoralisApiError(f"Moralis NFT stats request failed: {exc}") from exc

    raise MoralisApiError(
        f"Moralis returned 0 NFTs for {contract} on {chain}. "
        "Your API key works for other endpoints but this collection has no indexed data — "
        "enable the NFT API in the Moralis dashboard or check plan and quota limits."
    )


@dataclass
class NftPage:
    tokens: list[dict] = field(default_factory=list)
    traits: list[dict] = field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0


def fetch_nft_page(
    contract: str,
    chain: str,
    api_key: str,
    cursor: str | None = None,
) -> NftPage:
    params: dict[str, object] = {
        "chain": _normalize_chain(chain),
        "format": "decimal",
        "normalizeMetadata": "false",
        "limit": PAGE_SIZE,
        "media_items": "false",
    }
    if cursor:
        params["cursor"] = cursor

    _timeout = httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=5.0)
    for attempt in range(3):
        try:
            resp = httpx.get(
                f"{MORALIS_BASE}/nft/{contract}",
                params=params,
                headers={"X-API-Key": api_key},
                timeout=_timeout,
            )
            resp.raise_for_status()
            break
        except (TransportError, httpx.TimeoutException) as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

    data = resp.json()
    if not cursor and not data.get("result"):
        _raise_if_empty_collection(contract, chain, data, api_key)

    contract_lc = contract.lower()
    tokens: list[dict] = []
    traits: list[dict] = []

    for item in data.get("result") or []:
        token_id = int(item["token_id"])
        owner = (item.get("owner_of") or "").lower() or None
        block = item.get("block_number")

        tokens.append({
            "contract_address": contract_lc,
            "token_id": token_id,
            "owner_address": owner,
            "snapshot_block": int(block) if block else None,
        })

        raw_meta = item.get("metadata")
        try:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else (raw_meta or {})
        except (json.JSONDecodeError, TypeError):
            meta = {}
        attributes = meta.get("attributes") or []
        for attr in attributes:
            category = (attr.get("trait_type") or "").strip().title()
            if not category:
                continue
            traits.append({
                "contract_address": contract_lc,
                "token_id": token_id,
                "trait_category": category,
                "trait_value": _normalize_value(attr.get("value")),
            })

    time.sleep(RATE_SLEEP)

    return NftPage(
        tokens=tokens,
        traits=traits,
        next_cursor=data.get("cursor") or None,
        total=int(data.get("total") or 0),
    )


@dataclass
class SalesPage:
    sales: list[dict] = field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0


def fetch_sales_page(
    contract: str,
    chain: str,
    api_key: str,
    cursor: str | None = None,
) -> SalesPage:
    params: dict[str, object] = {
        "chain": _normalize_chain(chain),
        "limit": PAGE_SIZE,
    }
    if cursor:
        params["cursor"] = cursor

    _timeout = httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=5.0)
    for attempt in range(3):
        try:
            resp = httpx.get(
                f"{MORALIS_BASE}/nft/{contract}/trades",
                params=params,
                headers={"X-API-Key": api_key},
                timeout=_timeout,
            )
            resp.raise_for_status()
            break
        except (TransportError, httpx.TimeoutException) as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

    data = resp.json()
    contract_lc = contract.lower()
    sales: list[dict] = []

    for item in data.get("result") or []:
        token_ids = item.get("token_ids") or []
        if not token_ids:
            continue
        try:
            token_id = int(token_ids[0])
        except (ValueError, TypeError):
            continue

        tx_hash = (item.get("transaction_hash") or "").lower() or None
        if not tx_hash:
            continue  # skip unanchored trades — no dedup key

        price_eth: float | None = None
        if item.get("price_formatted"):
            try:
                price_eth = float(item["price_formatted"])
            except (ValueError, TypeError):
                pass
        if price_eth is None and item.get("price"):
            try:
                price_eth = int(item["price"]) / 1e18
            except (ValueError, TypeError):
                pass
        if price_eth is None:
            continue

        sold_at: datetime | None = None
        raw_ts = item.get("block_timestamp")
        if raw_ts:
            try:
                sold_at = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        sales.append({
            "contract_address": contract_lc,
            "token_id": token_id,
            "sale_price_eth": price_eth,
            "seller_address": (item.get("seller_address") or "").lower() or None,
            "buyer_address": (item.get("buyer_address") or "").lower() or None,
            "marketplace": item.get("marketplace_address") or None,
            "tx_hash": tx_hash,
            "sold_at": sold_at,
        })

    time.sleep(RATE_SLEEP)

    return SalesPage(
        sales=sales,
        next_cursor=data.get("cursor") or None,
        total=int(data.get("total") or 0),
    )
