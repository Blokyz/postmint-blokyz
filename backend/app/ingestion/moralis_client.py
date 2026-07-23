"""Moralis NFT API v2.2 client — paginated token + trait fetcher."""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from httpx import HTTPStatusError, TransportError

from app.config import get_settings
from app.ingestion.errors import MoralisApiError

MORALIS_BASE = "https://deep-index.moralis.io/api/v2.2"
PAGE_SIZE = 100
MAX_ATTEMPTS = 5
MAX_BACKOFF = 30.0  # cap on any single retry pause, incl. Retry-After
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    """Backoff before retrying a retryable HTTP status.

    Honors a numeric ``Retry-After`` header when present (Moralis sends one on
    429), otherwise exponential 1s/2s/4s/..., always capped at MAX_BACKOFF.
    """
    retry_after = resp.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), MAX_BACKOFF)
        except ValueError:
            pass  # HTTP-date form — fall through to exponential backoff
    return min(2.0 ** attempt, MAX_BACKOFF)


def _get_with_retry(
    url: str,
    params: dict[str, object],
    api_key: str,
    timeout: httpx.Timeout,
) -> httpx.Response:
    """GET with retries for transport errors and retryable HTTP statuses.

    Transport errors/timeouts and 429/5xx responses are retried up to
    MAX_ATTEMPTS with backoff; a persistent 429 surfaces as MoralisApiError
    (rate limit — actionable), other exhausted/non-retryable statuses raise
    HTTPStatusError as before.
    """
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = httpx.get(url, params=params, headers={"X-API-Key": api_key}, timeout=timeout)
        except (TransportError, httpx.TimeoutException):
            if attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(min(2.0 ** attempt, MAX_BACKOFF))
            continue

        if resp.status_code in _RETRYABLE_STATUS and attempt < MAX_ATTEMPTS - 1:
            time.sleep(_retry_delay(resp, attempt))
            continue

        if resp.status_code == 429:
            raise MoralisApiError(
                f"Moralis rate limit (HTTP 429) persisted after {MAX_ATTEMPTS} attempts "
                "— reduce request rate (MORALIS_RATE_SLEEP) or upgrade the plan."
            )
        resp.raise_for_status()
        return resp

    raise AssertionError("unreachable")  # loop always returns or raises


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
        stats_resp = _get_with_retry(
            f"{MORALIS_BASE}/nft/{contract}/stats",
            params={"chain": _normalize_chain(chain)},
            api_key=api_key,
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
        )
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

    resp = _get_with_retry(
        f"{MORALIS_BASE}/nft/{contract}",
        params=params,
        api_key=api_key,
        timeout=httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=5.0),
    )

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

    time.sleep(get_settings().moralis_rate_sleep)

    return NftPage(
        tokens=tokens,
        traits=traits,
        next_cursor=data.get("cursor") or None,
        total=int(data.get("total") or 0),
    )


@dataclass
class TransfersPage:
    transfers: list[dict] = field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0


def fetch_transfers_page(
    contract: str,
    chain: str,
    api_key: str,
    cursor: str | None = None,
    from_block: int | None = None,
) -> TransfersPage:
    """Fetch a page of NFT transfers (ownership changes) for the holding-window
    engine. `from_block` (inclusive) resumes from the last processed block so the
    poller doesn't re-scan history. Results are ordered oldest-first so callers can
    apply them chronologically and record a high-water block."""
    params: dict[str, object] = {
        "chain": _normalize_chain(chain),
        "format": "decimal",
        "order": "ASC",
        "limit": PAGE_SIZE,
    }
    if from_block is not None:
        params["from_block"] = from_block
    if cursor:
        params["cursor"] = cursor

    resp = _get_with_retry(
        f"{MORALIS_BASE}/nft/{contract}/transfers",
        params=params,
        api_key=api_key,
        timeout=httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=5.0),
    )

    data = resp.json()
    transfers: list[dict] = []

    for item in data.get("result") or []:
        raw_id = item.get("token_id")
        try:
            token_id = int(raw_id)
        except (ValueError, TypeError):
            continue

        block_number = item.get("block_number")
        try:
            block_number = int(block_number) if block_number is not None else None
        except (ValueError, TypeError):
            block_number = None

        log_index = item.get("log_index")
        try:
            log_index = int(log_index) if log_index is not None else 0
        except (ValueError, TypeError):
            log_index = 0

        transfers.append({
            "token_id": token_id,
            "from_address": (item.get("from_address") or "").lower() or None,
            "to_address": (item.get("to_address") or "").lower() or None,
            "block_number": block_number,
            "log_index": log_index,
            "tx_hash": (item.get("transaction_hash") or "").lower() or None,
        })

    time.sleep(get_settings().moralis_rate_sleep)

    return TransfersPage(
        transfers=transfers,
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

    resp = _get_with_retry(
        f"{MORALIS_BASE}/nft/{contract}/trades",
        params=params,
        api_key=api_key,
        timeout=httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=5.0),
    )

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

    time.sleep(get_settings().moralis_rate_sleep)

    return SalesPage(
        sales=sales,
        next_cursor=data.get("cursor") or None,
        total=int(data.get("total") or 0),
    )
