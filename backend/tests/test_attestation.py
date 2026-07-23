"""Unit tests for app.attestation — no DB required.

Mirrors the on-chain `ManifestRegistry.lockDigest` / signature recovery so that a
signature produced here is exactly what the contract will accept.
"""

import pytest
from eth_account import Account
from eth_utils import keccak

from app.attestation import (
    backend_signer_address,
    build_lock_digest,
    recover_lock_signer,
    sign_lock_attestation,
)

_KEY = "0x" + "22" * 32
_ADDR = Account.from_key(_KEY).address.lower()

_CHAIN_ID = 84532
_REGISTRY = "0x1111111111111111111111111111111111111111"
_NFT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936bc46"
_RANKING = "0x" + "ab" * 32
_ATLAS = "0x" + "cd" * 32


def test_digest_matches_solidity_abi_encode_packed():
    """build_lock_digest == keccak(uint256||address||address||bytes32||bytes32)."""
    expected = keccak(
        _CHAIN_ID.to_bytes(32, "big")
        + bytes.fromhex(_REGISTRY[2:])
        + bytes.fromhex(_NFT[2:])
        + bytes.fromhex(_RANKING[2:])
        + bytes.fromhex(_ATLAS[2:])
    )
    assert build_lock_digest(_CHAIN_ID, _REGISTRY, _NFT, _RANKING, _ATLAS) == expected


def test_digest_is_32_bytes():
    assert len(build_lock_digest(_CHAIN_ID, _REGISTRY, _NFT, _RANKING, _ATLAS)) == 32


def test_roundtrip_recovers_signer():
    sig = sign_lock_attestation(_KEY, _CHAIN_ID, _REGISTRY, _NFT, _RANKING, _ATLAS)
    assert sig.startswith("0x") and len(sig) == 132  # 0x + 65 bytes
    recovered = recover_lock_signer(_CHAIN_ID, _REGISTRY, _NFT, _RANKING, _ATLAS, sig)
    assert recovered == _ADDR


def test_backend_signer_address_matches_key():
    assert backend_signer_address(_KEY) == _ADDR


@pytest.mark.parametrize(
    "field,bad",
    [
        ("chain_id", 1),
        ("registry", "0x2222222222222222222222222222222222222222"),
        ("nft", "0x000000000000000000000000000000000000dead"),
        ("ranking", "0x" + "00" * 32),
        ("atlas", "0x" + "11" * 32),
    ],
)
def test_changing_any_field_changes_recovered_address(field, bad):
    """Attestation is bound to every field: verifying against tampered data
    yields a different (non-matching) address."""
    sig = sign_lock_attestation(_KEY, _CHAIN_ID, _REGISTRY, _NFT, _RANKING, _ATLAS)
    args = {
        "chain_id": _CHAIN_ID,
        "registry": _REGISTRY,
        "nft": _NFT,
        "ranking": _RANKING,
        "atlas": _ATLAS,
    }
    args[field] = bad
    recovered = recover_lock_signer(
        args["chain_id"], args["registry"], args["nft"], args["ranking"], args["atlas"], sig
    )
    assert recovered != _ADDR


def test_address_case_insensitive():
    sig = sign_lock_attestation(_KEY, _CHAIN_ID, _REGISTRY, _NFT.upper(), _RANKING, _ATLAS)
    recovered = recover_lock_signer(_CHAIN_ID, _REGISTRY, _NFT.lower(), _RANKING, _ATLAS, sig)
    assert recovered == _ADDR


def test_bad_hash_length_raises():
    with pytest.raises(ValueError):
        build_lock_digest(_CHAIN_ID, _REGISTRY, _NFT, "0x1234", _ATLAS)


def test_bad_address_length_raises():
    with pytest.raises(ValueError):
        build_lock_digest(_CHAIN_ID, "0x1234", _NFT, _RANKING, _ATLAS)


def test_nonpositive_chain_id_raises():
    with pytest.raises(ValueError):
        build_lock_digest(0, _REGISTRY, _NFT, _RANKING, _ATLAS)
