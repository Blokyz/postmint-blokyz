"""Unit tests for app.signing — no DB required."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.signing import (
    build_approval_message,
    build_ingest_message,
    build_publish_message,
    recover_approval_signer,
    recover_ingest_signer,
    recover_publish_signer,
)

_KEY = "0x" + "11" * 32
_ADDR = Account.from_key(_KEY).address.lower()
_CONTRACT = "0xbc4ca0eda7647a8ab7c2061c2e118a18a936f13d"

_ORDER = [("Eyes", "Laser", True), ("Background", "Red", False), ("Background", "Blue", False)]
_WS, _WM = 0.5, 0.5  # default stat/market weights


def _sign(message: str, key: str = _KEY) -> str:
    sig = Account.sign_message(encode_defunct(text=message), private_key=key).signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


def test_message_is_deterministic():
    a = build_approval_message(_CONTRACT, _ORDER, _WS, _WM)
    b = build_approval_message(_CONTRACT, list(_ORDER), _WS, _WM)
    assert a == b


def test_message_lowercases_contract_and_includes_order_and_weights():
    msg = build_approval_message(_CONTRACT.upper(), _ORDER, _WS, _WM)
    assert _CONTRACT in msg  # lowercased
    assert '["Eyes","Laser",true]' in msg
    assert "weights:0.50,0.50" in msg  # fixed 2-dp formatting


def test_whole_number_weights_are_two_dp():
    # Regression: JS JSON.stringify(1.0)=="1" but %.2f / toFixed(2) agree.
    msg = build_approval_message(_CONTRACT, _ORDER, 1.0, 0.0)
    assert "weights:1.00,0.00" in msg


def test_roundtrip_recovers_signer():
    msg = build_approval_message(_CONTRACT, _ORDER, _WS, _WM)
    recovered = recover_approval_signer(_CONTRACT, _ORDER, _WS, _WM, _sign(msg))
    assert recovered == _ADDR


def test_reordering_changes_recovered_address():
    """Signature is bound to order: signing one order then recovering against a
    different order yields a different (non-matching) address."""
    msg = build_approval_message(_CONTRACT, _ORDER, _WS, _WM)
    sig = _sign(msg)
    reordered = list(reversed(_ORDER))
    assert recover_approval_signer(_CONTRACT, reordered, _WS, _WM, sig) != _ADDR


def test_flipping_pinned_changes_recovered_address():
    msg = build_approval_message(_CONTRACT, _ORDER, _WS, _WM)
    sig = _sign(msg)
    flipped = [(_ORDER[0][0], _ORDER[0][1], False), *_ORDER[1:]]
    assert recover_approval_signer(_CONTRACT, flipped, _WS, _WM, sig) != _ADDR


def test_changing_weights_changes_recovered_address():
    """Signature is bound to the weights too: verifying with different weights
    than were signed yields a different (non-matching) address."""
    msg = build_approval_message(_CONTRACT, _ORDER, _WS, _WM)
    sig = _sign(msg)
    assert recover_approval_signer(_CONTRACT, _ORDER, 0.7, 0.3, sig) != _ADDR


def test_undecodable_signature_raises():
    with pytest.raises(Exception):
        recover_approval_signer(_CONTRACT, _ORDER, _WS, _WM, "0x" + "00" * 65)


# --- publish message (operator authorization) ---


def test_publish_message_lowercases_contract_and_binds_fields():
    msg = build_publish_message(_CONTRACT.upper(), "good-vibes", "Good Vibes")
    assert _CONTRACT in msg  # lowercased
    assert "slug:good-vibes" in msg
    assert "name:Good Vibes" in msg


def test_publish_roundtrip_recovers_signer():
    msg = build_publish_message(_CONTRACT, "good-vibes", "Good Vibes")
    assert recover_publish_signer(_CONTRACT, "good-vibes", "Good Vibes", _sign(msg)) == _ADDR


def test_publish_signature_bound_to_slug_and_name():
    sig = _sign(build_publish_message(_CONTRACT, "good-vibes", "Good Vibes"))
    # A signature for one slug/name doesn't recover the signer for another.
    assert recover_publish_signer(_CONTRACT, "evil-slug", "Good Vibes", sig) != _ADDR
    assert recover_publish_signer(_CONTRACT, "good-vibes", "Evil Name", sig) != _ADDR


# --- ingest message (operator authorization) ---

_ISSUED_AT = 1754200000


def test_ingest_message_lowercases_contract_and_binds_fields():
    msg = build_ingest_message(_CONTRACT.upper(), "eth", _ISSUED_AT)
    assert _CONTRACT in msg  # lowercased
    assert "chain:eth" in msg
    assert f"issued_at:{_ISSUED_AT}" in msg


def test_ingest_roundtrip_recovers_signer():
    msg = build_ingest_message(_CONTRACT, "eth", _ISSUED_AT)
    assert recover_ingest_signer(_CONTRACT, "eth", _ISSUED_AT, _sign(msg)) == _ADDR


def test_ingest_signature_bound_to_chain_and_timestamp():
    sig = _sign(build_ingest_message(_CONTRACT, "eth", _ISSUED_AT))
    # A signature for one chain/timestamp doesn't recover the signer for another
    # (this is what makes the replay window real — re-stamping needs a re-sign).
    assert recover_ingest_signer(_CONTRACT, "base", _ISSUED_AT, sig) != _ADDR
    assert recover_ingest_signer(_CONTRACT, "eth", _ISSUED_AT + 1, sig) != _ADDR
