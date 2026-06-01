"""Batch upsert helpers for tokens and traits."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Trait, Token


def upsert_tokens(db: Session, tokens: list[dict]) -> None:
    if not tokens:
        return
    stmt = insert(Token).values(tokens)
    stmt = stmt.on_conflict_do_update(
        index_elements=["contract_address", "token_id"],
        set_={
            "owner_address": stmt.excluded.owner_address,
            "snapshot_block": stmt.excluded.snapshot_block,
        },
    )
    db.execute(stmt)
    db.commit()


def upsert_traits(db: Session, traits: list[dict]) -> None:
    if not traits:
        return
    stmt = insert(Trait).values(traits)
    stmt = stmt.on_conflict_do_update(
        index_elements=["contract_address", "token_id", "trait_category"],
        set_={"trait_value": stmt.excluded.trait_value},
    )
    db.execute(stmt)
    db.commit()
