"""Backend lock attestation: authorize on-chain `ManifestRegistry.lockManifest`.

The off-chain approval flow (see ``app.signing``) authenticates the project owner
via their EIP-191 ranking signature. This module is the *on-chain* counterpart:
once an approval is verified, the trusted backend key signs the exact lock tuple
so that `ManifestRegistry.lockManifest` will accept it. The project owner submits
the transaction (and pays gas) carrying this signature; the contract recovers the
signer and reverts unless it matches its configured ``backendSigner``.

The signed digest mirrors the contract's ``lockDigest``:

    keccak256(abi.encodePacked(chainId, registryAddress, nftContract,
                               rankingHash, atlasHash))

then wrapped with the EIP-191 ``personal_sign`` prefix. Binding in ``chainId`` and
``registryAddress`` stops an attestation from being replayed on another chain or a
redeployed registry. Keep this byte-for-byte in lockstep with
``contracts/src/ManifestRegistry.sol``.
"""

from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

_HASH_RE_LEN = 32  # bytes
_ADDR_LEN = 20  # bytes


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


def build_lock_digest(
    chain_id: int,
    registry_address: str,
    nft_contract: str,
    ranking_hash: str,
    atlas_hash: str,
) -> bytes:
    """Recompute the contract's ``lockDigest`` (the pre-EIP-191 inner hash).

    ``abi.encodePacked(uint256, address, address, bytes32, bytes32)`` →
    32 + 20 + 20 + 32 + 32 bytes, then keccak256.
    """
    if chain_id <= 0:
        raise ValueError("chain_id must be a positive integer")
    packed = (
        chain_id.to_bytes(32, "big")
        + _hex_to_bytes(registry_address, _ADDR_LEN, "registry_address")
        + _hex_to_bytes(nft_contract, _ADDR_LEN, "nft_contract")
        + _hex_to_bytes(ranking_hash, _HASH_RE_LEN, "ranking_hash")
        + _hex_to_bytes(atlas_hash, _HASH_RE_LEN, "atlas_hash")
    )
    return keccak(packed)


def sign_lock_attestation(
    private_key: str,
    chain_id: int,
    registry_address: str,
    nft_contract: str,
    ranking_hash: str,
    atlas_hash: str,
) -> str:
    """Backend-sign the lock tuple; returns a 0x 65-byte EIP-191 signature."""
    digest = build_lock_digest(chain_id, registry_address, nft_contract, ranking_hash, atlas_hash)
    signed = Account.sign_message(encode_defunct(primitive=digest), private_key=private_key)
    # HexBytes.hex() returns with-or-without "0x" depending on the installed
    # version; normalize to a single 0x-prefixed string.
    return "0x" + signed.signature.hex().removeprefix("0x")


def recover_lock_signer(
    chain_id: int,
    registry_address: str,
    nft_contract: str,
    ranking_hash: str,
    atlas_hash: str,
    signature: str,
) -> str:
    """Recover the lowercased signer from a lock attestation (mirror of the contract)."""
    digest = build_lock_digest(chain_id, registry_address, nft_contract, ranking_hash, atlas_hash)
    recovered = Account.recover_message(encode_defunct(primitive=digest), signature=signature)
    return recovered.lower()


def backend_signer_address(private_key: str) -> str:
    """Lowercased address of the configured backend signer key."""
    return Account.from_key(private_key).address.lower()
