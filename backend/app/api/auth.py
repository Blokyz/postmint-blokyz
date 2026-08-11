"""Operator authorization for platform write actions (Wave-2 auth remainder).

The operator/platform write endpoints (approve a ranking, publish a collection,
register a season) were unauthenticated or authenticated-without-authorization.
These helpers add a real gate.

ENFORCE-WHEN-CONFIGURED: with an empty allowlist/token (the dev/test default)
they are no-ops, so existing flows are unchanged. Set them before mainnet.
  - ``operator_allowlist`` authorizes wallet-signed actions (ingest, approve,
    publish) against the recovered EIP-191 signer — you must be who you say AND
    allowed.
  - ``operator_api_token`` gates the server-to-server season registration, which
    is driven by the deploy script and has no wallet to sign with.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings

router = APIRouter()


def operator_gate_enabled() -> bool:
    """True when the allowlist is configured (i.e. wallet actions are gated)."""
    return bool(get_settings().operator_allowlist_set)


def assert_operator(address: str) -> None:
    """Raise 403 unless ``address`` is an allowed operator.

    No-op when the allowlist is unset (dev/test). Call this AFTER recovering the
    signer from a verified signature — it authorizes, it does not authenticate.
    """
    allow = get_settings().operator_allowlist_set
    if allow and address.lower() not in allow:
        raise HTTPException(status_code=403, detail="Address is not an authorized operator.")


@router.get("/auth/operator/{wallet}")
def operator_check(wallet: str) -> dict:
    """UX hint for the studio frontend gate: is this wallet an allowed operator?

    NOT an authorization grant — every operator write stays gated by signature
    + assert_operator. Empty allowlist = open, matching assert_operator.
    """
    allow = get_settings().operator_allowlist_set
    return {"allowed": not allow or wallet.lower() in allow}


def require_operator_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: require ``Authorization: Bearer <operator_api_token>``
    when that token is configured. No-op when unset (dev/test)."""
    token = get_settings().operator_api_token
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Missing or invalid operator token.")
