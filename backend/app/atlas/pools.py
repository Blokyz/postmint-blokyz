"""DB query helpers for set-atlas pool/feasibility computations.

A "pool" is a list of (trait_category, trait_value) tuples — the trait pairs
that belong to a tier's rarity band.
"""

from __future__ import annotations

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.db.models import Token, Trait

Pool = list[tuple[str, str]]


def excluded_token_ids_subq(contract: str, exclude_pool: Pool):
    """Subquery of token ids carrying >=1 trait in `exclude_pool`.

    Exclusive tier bands (Option A, 2026-08-13): a token belongs only to the
    band of its RAREST trait, so band pools exclude any token that also carries
    a trait from a rarer band. `exclude_pool` is that rarer-bands trait list
    (the tier's `set_rule.pool_exclude`)."""
    return (
        select(Trait.token_id)
        .where(Trait.contract_address == contract)
        .where(tuple_(Trait.trait_category, Trait.trait_value).in_(exclude_pool))
    )


def pool_token_ids(
    db: Session, contract: str, pool: Pool, exclude_pool: Pool | None = None
) -> list[int]:
    """Sorted distinct token ids with at least one trait in `pool` (and, when
    `exclude_pool` is given, none in it) — the tier's full membership, used by
    the public tier gallery."""
    if not pool:
        return []
    stmt = (
        select(Trait.token_id)
        .distinct()
        .where(Trait.contract_address == contract)
        .where(tuple_(Trait.trait_category, Trait.trait_value).in_(pool))
    )
    if exclude_pool:
        stmt = stmt.where(Trait.token_id.not_in(excluded_token_ids_subq(contract, exclude_pool)))
    return sorted(r[0] for r in db.execute(stmt).all())


def pool_token_count(
    db: Session, contract: str, pool: Pool, exclude_pool: Pool | None = None
) -> int:
    """Number of distinct tokens that have at least one trait in `pool`
    (and, when `exclude_pool` is given, no trait in it)."""
    if not pool:
        return 0
    stmt = (
        select(func.count(func.distinct(Trait.token_id)))
        .where(Trait.contract_address == contract)
        .where(tuple_(Trait.trait_category, Trait.trait_value).in_(pool))
    )
    if exclude_pool:
        stmt = stmt.where(Trait.token_id.not_in(excluded_token_ids_subq(contract, exclude_pool)))
    return db.scalar(stmt) or 0


def wallet_counts_for_pool(
    db: Session,
    contract: str,
    pool: Pool,
    exclude_token_ids: set[int] | None = None,
    exclude_pool: Pool | None = None,
) -> dict[str, int]:
    """Map wallet -> count of distinct tokens it holds with a trait in `pool`.

    `exclude_token_ids` drops specific tokens from the count — used by the race
    surfaces to ignore tokens already consumed by a won claim in the tier
    (atlas feasibility passes nothing: it estimates the pre-season universe).
    `exclude_pool` drops tokens carrying any rarer-band trait (exclusive bands)."""
    if not pool:
        return {}
    stmt = (
        select(Token.owner_address, func.count(func.distinct(Trait.token_id)))
        .join(
            Trait,
            (Trait.contract_address == Token.contract_address)
            & (Trait.token_id == Token.token_id),
        )
        .where(Token.contract_address == contract)
        .where(Token.owner_address.is_not(None))
        .where(tuple_(Trait.trait_category, Trait.trait_value).in_(pool))
    )
    if exclude_token_ids:
        stmt = stmt.where(Token.token_id.not_in(exclude_token_ids))
    if exclude_pool:
        stmt = stmt.where(Token.token_id.not_in(excluded_token_ids_subq(contract, exclude_pool)))
    rows = db.execute(stmt.group_by(Token.owner_address)).all()
    return {row[0]: row[1] for row in rows}


def rarest_trait_token_counts(
    db: Session, contract: str, ordered_pool: Pool
) -> dict[tuple[str, str], int]:
    """Map each trait pair -> count of tokens whose RAREST trait it is, under
    the rarity order given by `ordered_pool` (index 0 = rarest).

    This is the token-mass each trait contributes to its band under exclusive
    bands (Option A): a token counts toward exactly one trait — its first in
    the ordering. Tokens carrying none of the listed traits count nowhere.
    Used by bands.slice_into_tiers to place token-share cut points."""
    order = {pair: i for i, pair in enumerate(ordered_pool)}
    best: dict[int, int] = {}
    rows = db.execute(
        select(Trait.token_id, Trait.trait_category, Trait.trait_value).where(
            Trait.contract_address == contract
        )
    )
    for token_id, cat, val in rows:
        idx = order.get((cat, val))
        if idx is None:
            continue
        cur = best.get(token_id)
        if cur is None or idx < cur:
            best[token_id] = idx
    counts: dict[tuple[str, str], int] = {pair: 0 for pair in ordered_pool}
    for idx in best.values():
        counts[ordered_pool[idx]] += 1
    return counts


def wallet_owners_for_trait(db: Session, contract: str, category: str, value: str) -> set[str]:
    """Set of wallet addresses holding >=1 token with this trait pair."""
    rows = db.execute(
        select(Token.owner_address)
        .join(
            Trait,
            (Trait.contract_address == Token.contract_address)
            & (Trait.token_id == Token.token_id),
        )
        .where(Token.contract_address == contract)
        .where(Token.owner_address.is_not(None))
        .where(Trait.trait_category == category)
        .where(Trait.trait_value == value)
        .distinct()
    ).all()
    return {row[0] for row in rows}
