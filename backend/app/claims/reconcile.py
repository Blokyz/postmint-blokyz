"""Claimed-event reconciliation — the on-chain backstop for missed confirms.

The frontend normally reports a landed claim via ``/claim/confirm``, but that
link can break: a tab closed mid-flow, or (the case that motivated this)
MetaMask Smart Accounts wrapping the tx through their DelegationManager so the
frontend waits on a hash that never mines while the REAL wrapped tx succeeds.
The chain is the source of truth, so this module scans the season manager's
``Claimed`` logs directly and records any win the DB is missing.

Trust argument: the manager reverts any ``claim()`` not signed by its
configured ``backendSigner``, so every ``Claimed`` event on a
factory-deployed manager was backend-authorized — recording it is safe even
when no sign-created row survives (e.g. the row was consumed by an earlier
win under the no-cap rule; the event's own ``windowStartedAt`` is kept).

Run it on demand (``POST /claims/reconcile/{contract}``) or on a cadence.
Stateless by design: scans a bounded recent window (default ~4.6 days on Base's
2s blocks) and skips anything already recorded, so any cadence is idempotent.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.claims.onchain import CLAIMED_TOPIC0, _rpc
from app.claims.seasons import latest_season
from app.db.models import Claim

DEFAULT_LOOKBACK_BLOCKS = 200_000
# sepolia.base.org rejects eth_getLogs ranges over 2000 blocks (-32602).
GETLOGS_CHUNK = 2_000


class NoSeason(Exception):
    """No registered SetClaimManager for this contract."""


def decode_claimed_log(log: dict) -> dict:
    """Decode one ``Claimed`` log into its useful fields.

    Data tuple: (string tier, uint256 slotNumber, uint256[] tokenIds,
    uint256 nonce, uint256 windowStartedAt) — the tier string is read from its
    dynamic offset so tier names never need guessing from the indexed hash.
    """
    data = bytes.fromhex((log.get("data") or "0x")[2:])
    tier_offset = int.from_bytes(data[0:32], "big")
    tier_len = int.from_bytes(data[tier_offset : tier_offset + 32], "big")
    tier = data[tier_offset + 32 : tier_offset + 32 + tier_len].decode("utf-8", "replace")
    ids_offset = int.from_bytes(data[64:96], "big")
    ids_len = int.from_bytes(data[ids_offset : ids_offset + 32], "big")
    token_ids = [
        int.from_bytes(data[ids_offset + 32 + i * 32 : ids_offset + 64 + i * 32], "big")
        for i in range(ids_len)
    ]
    return {
        "tier": tier,
        "wallet": "0x" + log["topics"][2][-40:].lower(),
        "slot_number": int.from_bytes(data[32:64], "big"),
        "token_ids": token_ids,
        "window_started_at": int.from_bytes(data[128:160], "big"),
        "tx_hash": (log.get("transactionHash") or "").lower(),
    }


def fetch_claimed_logs(rpc_url: str, manager: str, from_block: int, to_block: int) -> list[dict]:
    """All ``Claimed`` logs emitted by ``manager`` in the range, chunk-paged."""
    logs: list[dict] = []
    start = from_block
    while start <= to_block:
        end = min(start + GETLOGS_CHUNK - 1, to_block)
        result = _rpc(
            rpc_url,
            "eth_getLogs",
            [
                {
                    "address": manager,
                    "topics": [CLAIMED_TOPIC0],
                    "fromBlock": hex(start),
                    "toBlock": hex(end),
                }
            ],
        )
        logs.extend(result or [])
        start = end + 1
    return logs


def reconcile_claims(
    db: Session,
    contract: str,
    rpc_url: str,
    lookback_blocks: int = DEFAULT_LOOKBACK_BLOCKS,
) -> dict:
    """Record any on-chain ``Claimed`` events missing from the DB.

    For each unrecorded event: mark the wallet's active (sign-created) claim
    row won, or create a fresh won row when none survives. Flushes; the caller
    commits (and should invalidate the race cache on any recording)."""
    contract = contract.lower()
    season = latest_season(db, contract)
    if season is None:
        raise NoSeason(contract)

    latest = int(str(_rpc(rpc_url, "eth_blockNumber", [])), 16)
    from_block = max(0, latest - lookback_blocks)
    logs = fetch_claimed_logs(rpc_url, season.manager_address, from_block, latest)

    recorded_slots = {
        (tier, slot)
        for tier, slot in db.execute(
            select(Claim.tier, Claim.slot_number)
            .where(Claim.contract_address == contract)
            .where(Claim.on_chain_tx_hash.is_not(None))
        ).all()
    }

    now = datetime.now(timezone.utc)
    recorded = []
    skipped = 0
    for log in logs:
        ev = decode_claimed_log(log)
        if (ev["tier"], ev["slot_number"]) in recorded_slots:
            skipped += 1
            continue

        row = db.scalar(
            select(Claim)
            .where(Claim.contract_address == contract)
            .where(Claim.tier == ev["tier"])
            .where(Claim.wallet_address == ev["wallet"])
            .where(Claim.on_chain_tx_hash.is_(None))
        )
        if row is None:
            # No surviving sign row (consumed by a prior win, or lost) — the
            # event itself is backend-authorized proof; record it whole.
            row = Claim(
                contract_address=contract,
                tier=ev["tier"],
                wallet_address=ev["wallet"],
                window_started=datetime.fromtimestamp(ev["window_started_at"], tz=timezone.utc),
            )
            db.add(row)
        row.on_chain_tx_hash = ev["tx_hash"]
        row.slot_number = ev["slot_number"]
        # The event lists exactly the tokens the claim consumed (they're bound
        # into the backend signature) — authoritative for set consumption.
        row.qualifying_tokens = ev["token_ids"]
        row.window_completed = now
        try:
            db.flush()
        except IntegrityError:
            db.rollback()  # concurrent recording of the same slot — skip
            skipped += 1
            continue
        recorded_slots.add((ev["tier"], ev["slot_number"]))
        recorded.append(
            {"tier": ev["tier"], "wallet": ev["wallet"], "slot_number": ev["slot_number"], "tx_hash": ev["tx_hash"]}
        )

    return {
        "contract_address": contract,
        "manager_address": season.manager_address,
        "scanned_from_block": from_block,
        "scanned_to_block": latest,
        "events": len(logs),
        "recorded": recorded,
        "already_recorded": skipped,
    }
