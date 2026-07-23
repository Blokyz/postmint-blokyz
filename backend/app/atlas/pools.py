"""DB query helpers for set-atlas pool/feasibility computations.

A "pool" is a list of (trait_category, trait_value) tuples — the trait pairs
that belong to a tier's rarity band.
"""

from __future__ import annotations

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.db.models import Token, Trait

Pool = list[tuple[str, str]]


def pool_token_count(db: Session, contract: str, pool: Pool) -> int:
    """Number of distinct tokens that have at least one trait in `pool`."""
    if not pool:
        return 0
    count = db.scalar(
        select(func.count(func.distinct(Trait.token_id)))
        .where(Trait.contract_address == contract)
        .where(tuple_(Trait.trait_category, Trait.trait_value).in_(pool))
    )
    return count or 0


def wallet_counts_for_pool(db: Session, contract: str, pool: Pool) -> dict[str, int]:
    """Map wallet -> count of distinct tokens it holds with a trait in `pool`."""
    if not pool:
        return {}
    rows = db.execute(
        select(Token.owner_address, func.count(func.distinct(Trait.token_id)))
        .join(
            Trait,
            (Trait.contract_address == Token.contract_address)
            & (Trait.token_id == Token.token_id),
        )
        .where(Token.contract_address == contract)
        .where(Token.owner_address.is_not(None))
        .where(tuple_(Trait.trait_category, Trait.trait_value).in_(pool))
        .group_by(Token.owner_address)
    ).all()
    return {row[0]: row[1] for row in rows}


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
