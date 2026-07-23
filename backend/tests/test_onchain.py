"""Unit tests for on-chain claim-tx verification (app.claims.onchain).

Network-free: they exercise verify_claim_receipt against hand-built receipt
dicts shaped exactly like an eth_getTransactionReceipt result, so the Claimed
event decoding + wallet/tier matching is covered without an RPC or a chain.
"""

import pytest
from eth_utils import keccak

from app.claims.onchain import (
    CLAIMED_TOPIC0,
    ClaimVerificationError,
    ReceiptNotFound,
    verify_claim_receipt,
)

MANAGER = "0x2222222222222222222222222222222222222222"
WALLET = "0x00000000000000000000000000000000000000a1"
TIER = "Rare"


def _word(n: int) -> bytes:
    return int(n).to_bytes(32, "big")


def _claimed_log(manager=MANAGER, tier=TIER, wallet=WALLET, slot=1, nonce=7, window=1_700_000_000):
    """A Claimed log matching event Claimed(bytes32,string,address,uint256,uint256[],uint256,uint256).

    Non-indexed data tuple = (string tier, uint256 slot, uint256[] tokenIds,
    uint256 nonce, uint256 window). The two dynamic params store an offset in the
    head, so the static values live at fixed words 1/3/4 — which is all the
    decoder reads, so the dynamic tails are irrelevant here.
    """
    tier_id = "0x" + keccak(text=tier).hex()
    wallet_topic = "0x" + wallet[2:].lower().rjust(64, "0")
    data = _word(0xA0) + _word(slot) + _word(0x100) + _word(nonce) + _word(window)
    return {
        "address": manager,
        "topics": [CLAIMED_TOPIC0, tier_id, wallet_topic],
        "data": "0x" + data.hex(),
    }


def _receipt(logs, status="0x1", to=MANAGER):
    return {"status": status, "to": to, "logs": logs, "transactionHash": "0x" + "ab" * 32}


def test_valid_receipt_returns_onchain_slot_and_nonce():
    out = verify_claim_receipt(_receipt([_claimed_log(slot=3, nonce=42)]), MANAGER, WALLET, TIER)
    assert out == {"slot_number": 3, "nonce": 42, "window_started_at": 1_700_000_000}


def test_none_receipt_is_retryable():
    with pytest.raises(ReceiptNotFound):
        verify_claim_receipt(None, MANAGER, WALLET, TIER)


def test_reverted_tx_rejected():
    with pytest.raises(ClaimVerificationError, match="reverted"):
        verify_claim_receipt(_receipt([_claimed_log()], status="0x0"), MANAGER, WALLET, TIER)


def test_no_claimed_event_rejected():
    with pytest.raises(ClaimVerificationError, match="no matching Claimed"):
        verify_claim_receipt(_receipt([]), MANAGER, WALLET, TIER)


def test_event_from_other_contract_ignored():
    """A Claimed log emitted by some OTHER address must not count."""
    log = _claimed_log(manager="0x9999999999999999999999999999999999999999")
    with pytest.raises(ClaimVerificationError):
        verify_claim_receipt(_receipt([log]), MANAGER, WALLET, TIER)


def test_wrong_wallet_rejected():
    other = "0x00000000000000000000000000000000000000ff"
    with pytest.raises(ClaimVerificationError):
        verify_claim_receipt(_receipt([_claimed_log(wallet=other)]), MANAGER, WALLET, TIER)


def test_wrong_tier_rejected():
    with pytest.raises(ClaimVerificationError):
        verify_claim_receipt(_receipt([_claimed_log(tier="Mythic")]), MANAGER, WALLET, TIER)


def test_case_insensitive_wallet_and_manager():
    out = verify_claim_receipt(
        _receipt([_claimed_log()]), MANAGER.upper(), WALLET.upper(), TIER
    )
    assert out["slot_number"] == 1


def test_matches_amongst_unrelated_logs():
    """Real receipts carry other logs (e.g. ERC-721 Transfer); pick the right one."""
    noise = {"address": MANAGER, "topics": ["0x" + "11" * 32], "data": "0x"}
    out = verify_claim_receipt(_receipt([noise, _claimed_log(slot=5)]), MANAGER, WALLET, TIER)
    assert out["slot_number"] == 5
