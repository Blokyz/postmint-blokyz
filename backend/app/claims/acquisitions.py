"""Acquisition timestamps — when did this wallet get each token?

Holding windows are derived from on-chain history instead of an explicit
START CLOCK opt-in: a tier's window starts the moment the wallet acquired its
X-th qualifying token (`set_completed_at`). `tokens.acquired_at` caches the
Transfer-event block timestamp per token; the transfer poller keeps it live for
every ownership change it sees, and `ensure_acquired_at` lazily backfills the
pre-existing NULLs (ingest records the owner, not since when) with one
wallet-scoped Moralis history walk.

Unknown stays conservative: any token whose acquisition can't be resolved is
stamped "now" — worst case a long holder waits one window once; a fresh buyer
can never skip the wait. Common (holding_window_hours=0) never needs this data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Token
from app.ingestion.moralis_client import fetch_wallet_transfers_page

# Bound on history pages walked per backfill (PAGE_SIZE transfers each). A
# wallet whose held tokens' inbound transfers sit deeper than this gets the
# conservative "now" stamp for the leftovers.
MAX_BACKFILL_PAGES = 20


def ensure_acquired_at(
    db: Session,
    contract: str,
    wallet: str,
    chain: str,
    api_key: str | None = None,
    max_pages: int = MAX_BACKFILL_PAGES,
) -> int:
    """Fill NULL `acquired_at` for tokens `wallet` currently holds in `contract`.

    Walks the wallet's transfer history newest-first, so the first inbound
    transfer seen per token is its latest acquisition (the one that matters —
    a sell-and-rebuy must count from the rebuy). No-op (zero API calls) when
    nothing is missing. Flushes; the caller commits. Returns the number of
    rows stamped.
    """
    contract = contract.lower()
    wallet = wallet.lower()

    missing = {
        r[0]
        for r in db.execute(
            select(Token.token_id)
            .where(Token.contract_address == contract)
            .where(Token.owner_address == wallet)
            .where(Token.acquired_at.is_(None))
        ).all()
    }
    if not missing:
        return 0

    api_key = api_key or get_settings().moralis_api_key

    resolved: dict[int, datetime] = {}
    cursor: str | None = None
    pages = 0
    while missing and pages < max_pages:
        page = fetch_wallet_transfers_page(wallet, contract, chain, api_key, cursor=cursor)
        for t in page.transfers:
            if t["to_address"] == wallet and t["token_id"] in missing and t["acquired_at"] is not None:
                resolved[t["token_id"]] = t["acquired_at"]
                missing.discard(t["token_id"])
        pages += 1
        cursor = page.next_cursor
        if not cursor:
            break

    # Unresolved (history exhausted, page cap hit, or timestamp-less transfers)
    # → conservative "now": the clock starts today rather than being skippable.
    now = datetime.now(timezone.utc)
    for token_id in missing:
        resolved[token_id] = now

    for token_id, acquired in resolved.items():
        token = db.get(Token, (contract, token_id))
        if token is not None and token.acquired_at is None:
            token.acquired_at = acquired
    db.flush()
    return len(resolved)


def _ordered_holdings(
    db: Session,
    contract: str,
    wallet: str,
    qualifying_token_ids: list[int],
) -> list[tuple[int, datetime]]:
    """The wallet's held qualifying tokens, oldest acquisition first. NULL
    `acquired_at` counts as "now" (run `ensure_acquired_at` first for real
    history); ties broken by token id for determinism."""
    rows = db.execute(
        select(Token.token_id, Token.acquired_at)
        .where(Token.contract_address == contract.lower())
        .where(Token.owner_address == wallet.lower())
        .where(Token.token_id.in_(qualifying_token_ids))
    ).all()
    now = datetime.now(timezone.utc)
    return sorted(
        ((token_id, acquired if acquired is not None else now) for token_id, acquired in rows),
        key=lambda r: (r[1], r[0]),
    )


def set_completed_at(
    db: Session,
    contract: str,
    wallet: str,
    qualifying_token_ids: list[int],
    count_required: int,
) -> datetime | None:
    """When did `wallet` complete this set — i.e. acquire its `count_required`-th
    qualifying token? The holding window runs from this moment. None when the
    wallet doesn't hold enough qualifying tokens.
    """
    if count_required <= 0 or len(qualifying_token_ids) < count_required:
        return None
    rows = _ordered_holdings(db, contract, wallet, qualifying_token_ids)
    if len(rows) < count_required:
        return None
    return rows[count_required - 1][1]


def oldest_qualifying_set(
    db: Session,
    contract: str,
    wallet: str,
    qualifying_token_ids: list[int],
    count_required: int,
) -> list[int]:
    """The exact set a claim spends: the `count_required` OLDEST-held qualifying
    tokens (the ones whose acquisition completed the set — same ordering as
    `set_completed_at`). A claim must never bind the wallet's WHOLE holding —
    a whale with 6 tokens on a 2-set tier spends 2 per win and keeps racing
    with the other 4. Empty when the wallet holds fewer than required.
    """
    if count_required <= 0 or len(qualifying_token_ids) < count_required:
        return []
    rows = _ordered_holdings(db, contract, wallet, qualifying_token_ids)
    if len(rows) < count_required:
        return []
    return sorted(token_id for token_id, _ in rows[:count_required])
