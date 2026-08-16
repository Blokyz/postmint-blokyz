"""Batch upsert helpers for tokens and traits."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Sale, Trait, Token


def upsert_tokens(db: Session, tokens: list[dict]) -> None:
    if not tokens:
        return
    stmt = insert(Token).values(tokens)
    stmt = stmt.on_conflict_do_update(
        index_elements=["contract_address", "token_id"],
        set_={
            "owner_address": stmt.excluded.owner_address,
            "snapshot_block": stmt.excluded.snapshot_block,
            "image_url": stmt.excluded.image_url,
        },
    )
    db.execute(stmt)
    db.commit()


def upsert_sales(db: Session, sales: list[dict]) -> None:
    if not sales:
        return
    stmt = insert(Sale).values(sales)
    stmt = stmt.on_conflict_do_nothing()
    db.execute(stmt)
    db.commit()


def upsert_traits(db: Session, traits: list[dict]) -> None:
    if not traits:
        return
    # Moralis can return duplicate trait_category entries for the same token.
    # ON CONFLICT DO UPDATE raises CardinalityViolation if two rows in the same
    # batch share the same conflict key, so deduplicate before inserting.
    seen: dict[tuple, dict] = {}
    for t in traits:
        seen[(t["contract_address"], t["token_id"], t["trait_category"])] = t
    traits = list(seen.values())
    stmt = insert(Trait).values(traits)
    stmt = stmt.on_conflict_do_update(
        index_elements=["contract_address", "token_id", "trait_category"],
        set_={"trait_value": stmt.excluded.trait_value},
    )
    db.execute(stmt)
    db.commit()
