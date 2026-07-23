"""On-chain verification of claim transactions (PROJECT_MASTER §6/§11).

``/claim/confirm`` records a win, and the DB is the source of truth for
physical-prize fulfilment — so a client-supplied ``tx_hash`` MUST be verified
against the chain before it is trusted. Without this, anyone who can open a
window (``/claim/submit``) could POST an arbitrary hash and be recorded as a
winner.

We do a raw JSON-RPC ``eth_getTransactionReceipt`` (httpx; no ``web3``
dependency, matching the rest of the codebase's self-contained approach) and
require the receipt to:
  - have succeeded (``status == 0x1``), and
  - carry a ``Claimed(...)`` log emitted BY the season ``SetClaimManager`` for
    exactly this ``wallet`` (indexed) and ``tier`` (indexed ``tierId``).

Because the manager reverts any ``claim()`` not signed by its configured
``backendSigner``, a genuine ``Claimed`` event on that manager for this wallet
proves the backend authorized it. The event's real ``slotNumber`` is returned so
the winner row records the authoritative on-chain slot rather than a
client-reported one (this also backfills the previously-null ``slot_number``).
"""

from __future__ import annotations

import httpx
from eth_utils import keccak

# keccak256 of the Claimed event signature (topic0). Field order/types must match
# `event Claimed(bytes32,string,address,uint256,uint256[],uint256,uint256)` in
# contracts/src/SetClaimManager.sol.
_CLAIMED_SIGNATURE = "Claimed(bytes32,string,address,uint256,uint256[],uint256,uint256)"
CLAIMED_TOPIC0 = "0x" + keccak(text=_CLAIMED_SIGNATURE).hex()

_RPC_TIMEOUT = 15.0


class ClaimVerificationError(Exception):
    """The claim tx failed verification (reverted, wrong target, or spoofed)."""


class ReceiptNotFound(Exception):
    """Receipt not yet available (tx not mined / RPC lag). Retryable."""


def _rpc(rpc_url: str, method: str, params: list) -> object:
    resp = httpx.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=_RPC_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise ClaimVerificationError(f"RPC error: {body['error']}")
    return body.get("result")


def fetch_receipt(rpc_url: str, tx_hash: str) -> dict | None:
    """Fetch a transaction receipt via JSON-RPC. None if not yet mined."""
    return _rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])  # type: ignore[return-value]


def _address_from_topic(topic: str) -> str:
    """An indexed address topic is the address left-padded to 32 bytes."""
    return "0x" + topic[-40:].lower()


def verify_claim_receipt(receipt: dict | None, manager_address: str, wallet: str, tier: str) -> dict:
    """Validate a receipt is a genuine ``Claimed`` for ``wallet``+``tier`` on the
    season manager. Returns ``{slot_number, nonce, window_started_at}`` on success
    and raises ``ClaimVerificationError`` / ``ReceiptNotFound`` otherwise.

    Pure over the receipt dict (no network), so it is unit-testable in isolation.
    """
    if receipt is None:
        raise ReceiptNotFound("transaction receipt not available yet")

    status = receipt.get("status")
    # JSON-RPC returns status as a hex string ("0x1"/"0x0"). A reverted claim
    # wouldn't emit Claimed anyway, but reject early for a clearer error.
    if status is not None and int(str(status), 16) != 1:
        raise ClaimVerificationError("transaction reverted on-chain")

    manager = manager_address.lower()
    want_tier_id = "0x" + keccak(text=tier).hex()
    want_wallet = wallet.lower()

    for log in receipt.get("logs", []):
        if (log.get("address") or "").lower() != manager:
            continue
        topics = [t.lower() for t in (log.get("topics") or [])]
        if len(topics) < 3:
            continue
        if topics[0] != CLAIMED_TOPIC0 or topics[1] != want_tier_id:
            continue
        if _address_from_topic(topics[2]) != want_wallet:
            continue
        # Non-indexed data tuple: (string tier, uint256 slotNumber, uint256[]
        # tokenIds, uint256 nonce, uint256 windowStartedAt). The two dynamic
        # params (tier, tokenIds) store only a 32-byte offset in the head, so the
        # static values sit at fixed word offsets: slotNumber=word1, nonce=word3,
        # windowStartedAt=word4.
        data = bytes.fromhex((log.get("data") or "0x")[2:])
        if len(data) < 160:
            raise ClaimVerificationError("malformed Claimed event data")
        return {
            "slot_number": int.from_bytes(data[32:64], "big"),
            "nonce": int.from_bytes(data[96:128], "big"),
            "window_started_at": int.from_bytes(data[128:160], "big"),
        }

    raise ClaimVerificationError("no matching Claimed event for this wallet + tier")


def verify_claim_tx(rpc_url: str, tx_hash: str, manager_address: str, wallet: str, tier: str) -> dict:
    """Fetch and verify a claim tx receipt. Raises on invalid/missing receipts."""
    receipt = fetch_receipt(rpc_url, tx_hash)
    return verify_claim_receipt(receipt, manager_address, wallet, tier)
