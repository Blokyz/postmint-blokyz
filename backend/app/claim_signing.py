"""Backend claim attestation: authorize on-chain `SetClaimManager.claim`.

This is the Phase-3 counterpart to ``app.attestation`` (which authorizes
``ManifestRegistry.lockManifest``). After the off-chain holding-window engine has
verified that ``wallet`` held a qualifying set for the tier's required window, the
trusted backend key signs the exact claim tuple so that ``SetClaimManager.claim``
will accept it. The holder submits the transaction (pays gas, is recorded as the
winner); the contract recovers the signer and reverts unless it matches its
configured ``backendSigner``.

The signed digest mirrors the contract's ``claimDigest`` byte-for-byte::

    keccak256(abi.encodePacked(
        uint256  chainId,
        address  managerAddress,        // the season SetClaimManager (address(this))
        address  nftContract,
        address  wallet,
        bytes32  keccak256(bytes(tier)),
        bytes32  keccak256(abi.encodePacked(tokenIds)),   // each id padded to 32 bytes
        uint256  windowStartedAt,
        uint256  expiry,
        uint256  nonce
    ))

then wrapped with the EIP-191 ``personal_sign`` prefix. Binding in ``chainId`` and
``managerAddress`` stops an attestation from being replayed on another chain or a
different season (each season is its own contract). Keep this byte-for-byte in
lockstep with ``contracts/src/SetClaimManager.sol`` — the golden vectors in
``backend/tests/fixtures/claim_digest_vectors.json`` are produced by the contract
itself and cross-checked in ``tests/test_claim_signing.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

_ADDR_LEN = 20  # bytes
_UINT256_MAX = (1 << 256) - 1


def _hex_to_bytes(value: str, expected_len: int, label: str) -> bytes:
    """Decode a 0x-prefixed hex string to fixed-length bytes (case-insensitive)."""
    raw = value[2:] if value.lower().startswith("0x") else value
    try:
        b = bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError(f"{label} is not valid hex: {value!r}") from exc
    if len(b) != expected_len:
        raise ValueError(f"{label} must be {expected_len} bytes, got {len(b)}")
    return b


def _uint256(value: int, label: str) -> bytes:
    """Encode a non-negative int as a 32-byte big-endian word (mirrors abi.encodePacked)."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an int, got {type(value).__name__}")
    if value < 0 or value > _UINT256_MAX:
        raise ValueError(f"{label} out of uint256 range: {value}")
    return value.to_bytes(32, "big")


def _pack_token_ids(token_ids: Sequence[int]) -> bytes:
    """keccak256(abi.encodePacked(uint256[] tokenIds)) — each id is a full 32-byte word."""
    packed = b"".join(_uint256(int(t), "token_id") for t in token_ids)
    return keccak(packed)


def build_claim_digest(
    chain_id: int,
    manager_address: str,
    nft_contract: str,
    wallet: str,
    tier: str,
    token_ids: Sequence[int],
    window_started_at: int,
    expiry: int,
    nonce: int,
) -> bytes:
    """Recompute the contract's ``claimDigest`` (the pre-EIP-191 inner hash).

    ``manager_address`` is the season ``SetClaimManager`` address (the contract's
    ``address(this)``), NOT the factory or the NFT collection.
    """
    if chain_id <= 0:
        raise ValueError("chain_id must be a positive integer")
    packed = (
        _uint256(chain_id, "chain_id")
        + _hex_to_bytes(manager_address, _ADDR_LEN, "manager_address")
        + _hex_to_bytes(nft_contract, _ADDR_LEN, "nft_contract")
        + _hex_to_bytes(wallet, _ADDR_LEN, "wallet")
        + keccak(tier.encode("utf-8"))
        + _pack_token_ids(token_ids)
        + _uint256(window_started_at, "window_started_at")
        + _uint256(expiry, "expiry")
        + _uint256(nonce, "nonce")
    )
    return keccak(packed)


def sign_claim_attestation(
    private_key: str,
    chain_id: int,
    manager_address: str,
    nft_contract: str,
    wallet: str,
    tier: str,
    token_ids: Sequence[int],
    window_started_at: int,
    expiry: int,
    nonce: int,
) -> str:
    """Backend-sign a claim tuple; returns a 0x 65-byte EIP-191 signature."""
    digest = build_claim_digest(
        chain_id,
        manager_address,
        nft_contract,
        wallet,
        tier,
        token_ids,
        window_started_at,
        expiry,
        nonce,
    )
    signed = Account.sign_message(encode_defunct(primitive=digest), private_key=private_key)
    # HexBytes.hex() returns with-or-without "0x" depending on the installed
    # version; normalize to a single 0x-prefixed string.
    return "0x" + signed.signature.hex().removeprefix("0x")


def recover_claim_signer(
    chain_id: int,
    manager_address: str,
    nft_contract: str,
    wallet: str,
    tier: str,
    token_ids: Sequence[int],
    window_started_at: int,
    expiry: int,
    nonce: int,
    signature: str,
) -> str:
    """Recover the lowercased signer from a claim attestation (mirror of the contract)."""
    digest = build_claim_digest(
        chain_id,
        manager_address,
        nft_contract,
        wallet,
        tier,
        token_ids,
        window_started_at,
        expiry,
        nonce,
    )
    recovered = Account.recover_message(encode_defunct(primitive=digest), signature=signature)
    return recovered.lower()


def backend_signer_address(private_key: str) -> str:
    """Lowercased address of the configured backend signer key."""
    return Account.from_key(private_key).address.lower()