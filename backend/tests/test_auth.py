"""Unit tests for app.api.auth operator gates — no DB required.

The gates are enforce-when-configured: empty allowlist/token = open (dev/test).
These mutate the cached Settings via monkeypatch and restore it (autouse).
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.auth import assert_operator, operator_gate_enabled, require_operator_token
from app.config import get_settings
from app.main import app

OP = "0x00000000000000000000000000000000000000a1"
OTHER = "0x00000000000000000000000000000000000000b2"


@pytest.fixture(autouse=True)
def _reset_settings():
    s = get_settings()
    allow, token = s.operator_allowlist, s.operator_api_token
    yield
    s.operator_allowlist, s.operator_api_token = allow, token


def _set(allowlist="", token=""):
    s = get_settings()
    s.operator_allowlist = allowlist
    s.operator_api_token = token


def test_allowlist_open_when_unset():
    _set(allowlist="")
    assert operator_gate_enabled() is False
    assert_operator(OTHER)  # no-op, does not raise


def test_allowlist_allows_member_case_insensitive():
    _set(allowlist=f"{OP.upper()},{OTHER}")
    assert operator_gate_enabled() is True
    assert_operator(OP)  # allowed


def test_allowlist_rejects_non_member():
    _set(allowlist=OP)
    with pytest.raises(HTTPException) as ei:
        assert_operator(OTHER)
    assert ei.value.status_code == 403


def test_operator_check_open_when_unset():
    _set(allowlist="")
    with TestClient(app) as client:
        assert client.get(f"/auth/operator/{OTHER}").json() == {"allowed": True}


def test_operator_check_membership():
    _set(allowlist=OP)
    with TestClient(app) as client:
        assert client.get(f"/auth/operator/{OP.upper()}").json() == {"allowed": True}
        assert client.get(f"/auth/operator/{OTHER}").json() == {"allowed": False}


def test_token_open_when_unset():
    _set(token="")
    require_operator_token(authorization=None)  # no-op


def test_token_required_when_set():
    _set(token="s3cret")
    with pytest.raises(HTTPException) as ei:
        require_operator_token(authorization=None)
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException):
        require_operator_token(authorization="Bearer wrong")
    require_operator_token(authorization="Bearer s3cret")  # correct → no raise
