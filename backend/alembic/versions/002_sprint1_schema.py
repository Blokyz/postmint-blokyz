"""sprint1 schema fixes

Revision ID: 002
Revises: 001
Create Date: 2026-05-23

- ingest_jobs: add last_cursor, manifest_path
- claims: drop wrong unique(contract, tier, wallet) — whales may win multiple slots
          add partial unique on slot_number (WHERE NOT NULL)
          add wallet lookup index
- traits: add lookup index (contract, category, value)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ingest_jobs", sa.Column("last_cursor", sa.Text(), nullable=True))
    op.add_column("ingest_jobs", sa.Column("manifest_path", sa.Text(), nullable=True))

    # Drop the overly-restrictive unique constraint that prevents whale multi-claims.
    # The constraint name Alembic auto-generates from (contract_address, tier, wallet_address).
    op.drop_constraint("claims_contract_address_tier_wallet_address_key", "claims", type_="unique")

    # Correct uniqueness: one row per awarded slot number (NULL slots = pending, no constraint).
    op.create_index(
        "uix_claims_contract_tier_slot",
        "claims",
        ["contract_address", "tier", "slot_number"],
        unique=True,
        postgresql_where=sa.text("slot_number IS NOT NULL"),
    )

    op.create_index(
        "ix_claims_contract_tier_wallet",
        "claims",
        ["contract_address", "tier", "wallet_address"],
    )

    op.create_index(
        "ix_traits_contract_category_value",
        "traits",
        ["contract_address", "trait_category", "trait_value"],
    )


def downgrade() -> None:
    op.drop_index("ix_traits_contract_category_value", table_name="traits")
    op.drop_index("ix_claims_contract_tier_wallet", table_name="claims")
    op.drop_index("uix_claims_contract_tier_slot", table_name="claims")
    op.create_unique_constraint(
        "claims_contract_address_tier_wallet_address_key",
        "claims",
        ["contract_address", "tier", "wallet_address"],
    )
    op.drop_column("ingest_jobs", "manifest_path")
    op.drop_column("ingest_jobs", "last_cursor")
