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


def build_publish_message(contract_address: str, slug: str, display_name: str) -> str:
    """Deterministic message an operator signs to publish a collection.

    Binds the contract + slug + display name being published so a signature can't
    be reused for a different collection. Plain lines (no JSON) so the frontend
    reproduces the bytes trivially — keep the client mirror in lockstep.
    """
    return (
        "PostMint collection publish\n"
        f"contract:{contract_address.lower()}\n"
        f"slug:{slug}\n"
        f"name:{display_name}"
    )


def recover_publish_signer(
    contract_address: str, slug: str, display_name: str, signature: str
) -> str:
    """Recover the lowercased signer of a publish message (see build_publish_message)."""
    message = build_publish_message(contract_address, slug, display_name)
    recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
    return recovered.lower()


def build_ingest_message(contract_address: str, chain: str, issued_at: int) -> str:
    """Deterministic message an operator signs to start an ingestion.

    Binds the contract + source chain so a signature can't authorize a different
    collection, and ``issued_at`` (unix seconds) so a captured signature goes
    stale — the API rejects messages older than ``ingest_sig_ttl_seconds``.
    Plain lines; keep the client mirror (lib/ingest.ts) in lockstep.
    """
    return (
        "PostMint collection ingest\n"
        f"contract:{contract_address.lower()}\n"
        f"chain:{chain}\n"
        f"issued_at:{issued_at}"
    )


def recover_ingest_signer(
    contract_address: str, chain: str, issued_at: int, signature: str
) -> str:
    """Recover the lowercased signer of an ingest message (see build_ingest_message)."""
    message = build_ingest_message(contract_address, chain, issued_at)
    recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
    return recovered.lower()
