"""Unit tests for app.signing — no DB required."""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.signing import build_approval_message, recover_approval_signer

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
