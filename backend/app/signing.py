"""Approval signature: prove ownership of `approver_address` via EIP-191.

The approver's wallet signs a deterministic message rebuilt from the contract
address and the *ordered* trait ranking they are approving. The API recovers the
signer from the signature and rejects the request unless it matches the claimed
`approver_address`. This binds the signature to the exact ranking submitted
(reorder one trait or flip one `pinned` flag and the recovered address changes),
without depending on the server-side `compute_manifest_hash` canonicalization.

The frontend must reproduce `build_approval_message` byte-for-byte before asking
the wallet to `personal_sign` it. Keep this format in lockstep with the client.
"""

from __future__ import annotations

import json

from eth_account import Account
from eth_account.messages import encode_defunct

# Ordered trait = (trait_category, trait_value, pinned).
OrderedTrait = tuple[str, str, bool]


def build_approval_message(
    contract_address: str,
    ordered_traits: list[OrderedTrait],
    w_stat: float,
    w_market: float,
) -> str:
    """Deterministic, human-readable message the approver signs.

    The `order` line is a compact JSON array of [category, value, pinned] in the
    exact rank order being approved. `json.dumps(separators=(",", ":"))` matches
    JavaScript `JSON.stringify` for arrays of strings/bools, so the frontend can
    reproduce these bytes exactly. Weights are formatted with fixed 2-dp
    precision (NOT JSON numbers) because JS `JSON.stringify` renders 1.0 as "1"
    while Python renders "1.0" — `%.2f` / `.toFixed(2)` agree for both.
    """
    order = [[c, v, bool(p)] for c, v, p in ordered_traits]
    order_json = json.dumps(order, separators=(",", ":"), ensure_ascii=False)
    return (
        "PostMint Set Atlas ranking approval\n"
        f"contract:{contract_address.lower()}\n"
        f"weights:{w_stat:.2f},{w_market:.2f}\n"
        f"order:{order_json}"
    )


def recover_approval_signer(
    contract_address: str,
    ordered_traits: list[OrderedTrait],
    w_stat: float,
    w_market: float,
    signature: str,
) -> str:
    """Recover the lowercased signer address from an EIP-191 personal_sign.

    Raises (ValueError / eth_account errors) on a malformed or undecodable
    signature; the caller maps that to an HTTP 400.
    """
    message = build_approval_message(contract_address, ordered_traits, w_stat, w_market)
    recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
    return recovered.lower()
