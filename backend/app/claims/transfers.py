"""Transfer polling — keeps token ownership + acquisition timestamps live.

Keeps `tokens.owner_address` and `tokens.acquired_at` current from Moralis NFT
transfer events. Resumable via the `transfer_sync` high-water block, so each
poll only scans new ownership changes.

Since 2026-08-04 windows are DERIVED from `acquired_at` (no persisted window
state), so the poller no longer resets anything — an out-transfer that drops a
wallet below X simply changes what the next status derivation computes.

Idempotent by design: re-applying a transfer sets the same final owner +
timestamp — so re-processing a boundary block (which the poller does, resuming
inclusively from `last_block`) is harmless.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Token, TransferSync
from app.ingestion.moralis_client import fetch_transfers_page

# Safety bound on pages fetched per poll cycle — a huge backlog is drained over
# several cycles (each resumes from the recorded high-water block).
MAX_POLL_PAGES = 50


def _load_sync(db: Session, contract: str) -> TransferSync:
    row = db.get(TransferSync, contract)
    if row is None:
        row = TransferSync(contract_address=contract, last_block=None, cursor=None)
        db.add(row)
    return row


def apply_transfer_ownership(db: Session, contract: str, transfers: list[dict]) -> int:
    """Set `tokens.owner_address` + `tokens.acquired_at` to the latest transfer
    per token.

    `transfers` must be chronological (oldest first) so the last write wins.
    `acquired_at` is always written on an ownership change — a transfer without a
    timestamp writes NULL rather than leaving the previous owner's timestamp in
    place (a stale acquired_at would credit the new owner with the old owner's
    holding time; NULL just triggers the lazy backfill). Returns the number of
    token rows updated (tokens not in our snapshot are skipped — no traits, so
    irrelevant to eligibility)."""
    latest: dict[int, dict] = {}
    for t in transfers:
        if t["to_address"] is not None:
            latest[t["token_id"]] = t

    updated = 0
    for token_id, t in latest.items():
        res = db.execute(
            update(Token)
            .where(Token.contract_address == contract, Token.token_id == token_id)
            .values(owner_address=t["to_address"], acquired_at=t.get("acquired_at"))
        )
        updated += res.rowcount or 0
    return updated


def poll_transfers(
    db: Session,
    contract: str,
    chain: str,
    api_key: str | None = None,
    max_pages: int = MAX_POLL_PAGES,
) -> dict:
    """Fetch new transfers and update ownership + acquisition timestamps.
    Flushes; the caller commits. Returns a summary dict."""
    contract = contract.lower()
    api_key = api_key or get_settings().moralis_api_key

    sync = _load_sync(db, contract)
    # Resume inclusively from the last processed block (re-processing the boundary
    # block is idempotent) so a mid-block pagination cut can't open a gap.
    from_block = sync.last_block if sync.last_block is not None else None

    transfers: list[dict] = []
    max_block = sync.last_block
    cursor: str | None = None
    pages = 0

    while pages < max_pages:
        page = fetch_transfers_page(contract, chain, api_key, cursor=cursor, from_block=from_block)
        transfers.extend(page.transfers)
        for t in page.transfers:
            if t["block_number"] is not None:
                max_block = t["block_number"] if max_block is None else max(max_block, t["block_number"])
        pages += 1
        cursor = page.next_cursor
        if not cursor:
            break

    tokens_updated = apply_transfer_ownership(db, contract, transfers)

    sync.last_block = max_block
    sync.cursor = None  # cursors aren't reused across cycles; from_block resumes us
    db.flush()

    return {
        "transfers": len(transfers),
        "tokens_updated": tokens_updated,
        "last_block": max_block,
        "pages": pages,
        "drained": cursor is None,
    }
