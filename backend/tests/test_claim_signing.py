"""Unit tests for app.claim_signing — no DB required.

Mirrors the on-chain `SetClaimManager.claimDigest` / signature recovery so that a
signature produced here is exactly what the contract will accept. The golden
vectors in fixtures/claim_digest_vectors.json are produced BY the contract itself
(contracts/test/ClaimDigestVector.t.sol) — the byte-for-byte cross-language proof.
"""

import json
from pathlib import Path

import pytest
from eth_account import Account
from eth_utils import keccak

from app.claim_signing import (
    backend_signer_address,
    build_claim_digest,
    recover_claim_signer,
    sign_claim_attestation,
)

_KEY = "0x" + "33" * 32
_ADDR = Account.from_key(_KEY).address.lower()

_CHAIN_ID = 84532
_MANAGER = "0x2222222222222222222222222222222222222222"
_NFT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
_WALLET = "0x1111111111111111111111111111111111111111"
_TIER = "Mythic"
_TOKENS = [1, 2, 3]
_WS = 1_000_000
_EXP = 1_003_600
_NONCE = 7

_FIXTURE = Path(__file__).parent / "fixtures" / "claim_digest_vectors.json"


def _digest(**over):
    args = {
        "chain_id": _CHAIN_ID,
        "manager_address": _MANAGER,
        "nft_contract": _NFT,
        "wallet": _WALLET,
        "tier": _TIER,
        "token_ids": _TOKENS,
        "window_started_at": _WS,
        "expiry": _EXP,
        "nonce": _NONCE,
    }
    args.update(over)
    return build_claim_digest(**args)


# --- Golden cross-check against the real contract ---


def test_matches_contract_golden_vectors():
    """build_claim_digest reproduces SetClaimManager.claimDigest byte-for-byte."""
    data = json.loads(_FIXTURE.read_text())
    for vec in data["vectors"]:
        digest = build_claim_digest(
            chain_id=data["chain_id"],
            manager_address=data["manager_address"],
            nft_contract=data["nft_contract"],
            wallet=data["wallet"],
            tier=vec["tier"],
            token_ids=vec["token_ids"],
            window_started_at=vec["window_started_at"],
            expiry=vec["expiry"],
            nonce=vec["nonce"],
        )
        assert "0x" + digest.hex() == vec["expected_digest"], vec["label"]


# --- Structural / semantic ---


def test_digest_matches_manual_abi_encode_packed():
    expected = keccak(
        _CHAIN_ID.to_bytes(32, "big")
        + bytes.fromhex(_MANAGER[2:])
        + bytes.fromhex(_NFT[2:])
        + bytes.fromhex(_WALLET[2:])
        + keccak(_TIER.encode("utf-8"))
        + keccak(b"".join(t.to_bytes(32, "big") for t in _TOKENS))
        + _WS.to_bytes(32, "big")
        + _EXP.to_bytes(32, "big")
        + _NONCE.to_bytes(32, "big")
    )
    assert _digest() == expected


def test_digest_is_32_bytes():
    assert len(_digest()) == 32


def test_roundtrip_recovers_signer():
    sig = sign_claim_attestation(
        _KEY, _CHAIN_ID, _MANAGER, _NFT, _WALLET, _TIER, _TOKENS, _WS, _EXP, _NONCE
    )
    assert sig.startswith("0x") and len(sig) == 132  # 0x + 65 bytes
    recovered = recover_claim_signer(
        _CHAIN_ID, _MANAGER, _NFT, _WALLET, _TIER, _TOKENS, _WS, _EXP, _NONCE, sig
    )
    assert recovered == _ADDR


def test_backend_signer_address_matches_key():
    assert backend_signer_address(_KEY) == _ADDR


@pytest.mark.parametrize(
    "field,bad",
    [
        ("chain_id", 1),
        ("manager_address", "0x3333333333333333333333333333333333333333"),
        ("nft_contract", "0x000000000000000000000000000000000000dead"),
        ("wallet", "0x2222222222222222222222222222222222222222"),
        ("tier", "Common"),
        ("token_ids", [1, 2, 4]),
        ("window_started_at", _WS + 1),
        ("expiry", _EXP + 1),
        ("nonce", _NONCE + 1),
    ],
)
def test_changing_any_field_changes_recovered_address(field, bad):
    """Attestation binds every field: verifying against tampered data yields a
    different (non-matching) address — the whole reason for the on-chain checks."""
    sig = sign_claim_attestation(
        _KEY, _CHAIN_ID, _MANAGER, _NFT, _WALLET, _TIER, _TOKENS, _WS, _EXP, _NONCE
    )
    args = {
        "chain_id": _CHAIN_ID,
        "manager_address": _MANAGER,
        "nft_contract": _NFT,
        "wallet": _WALLET,
        "tier": _TIER,
        "token_ids": _TOKENS,
        "window_started_at": _WS,
        "expiry": _EXP,
        "nonce": _NONCE,
    }
    args[field] = bad
    recovered = recover_claim_signer(
        args["chain_id"],
        args["manager_address"],
        args["nft_contract"],
        args["wallet"],
        args["tier"],
        args["token_ids"],
        args["window_started_at"],
        args["expiry"],
        args["nonce"],
        sig,
    )
    assert recovered != _ADDR


def test_token_id_order_matters():
    """Packed token ids are order-sensitive (matches abi.encodePacked)."""
    assert _digest(token_ids=[1, 2, 3]) != _digest(token_ids=[3, 2, 1])


def test_address_case_insensitive():
    sig = sign_claim_attestation(
        _KEY, _CHAIN_ID, _MANAGER, _NFT.upper(), _WALLET, _TIER, _TOKENS, _WS, _EXP, _NONCE
    )
    recovered = recover_claim_signer(
        _CHAIN_ID, _MANAGER, _NFT.lower(), _WALLET, _TIER, _TOKENS, _WS, _EXP, _NONCE, sig
    )
    assert recovered == _ADDR


# --- Validation ---


def test_bad_address_length_raises():
    with pytest.raises(ValueError):
        _digest(manager_address="0x1234")


def test_nonpositive_chain_id_raises():
    with pytest.raises(ValueError):
        _digest(chain_id=0)


def test_negative_token_id_raises():
    with pytest.raises(ValueError):
        _digest(token_ids=[-1])


def test_token_id_over_uint256_raises():
    with pytest.raises(ValueError):
        _digest(token_ids=[1 << 256])


def test_bool_nonce_rejected():
    """bool is an int subclass in Python; reject it so True can't masquerade as 1."""
    with pytest.raises(ValueError):
        _digest(nonce=True)
