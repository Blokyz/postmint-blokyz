"""seasons + claim_nonces tables (Phase 3 claim API)

Revision ID: 006
Revises: 005
Create Date: 2026-07-16

Backs the claim API:
- `seasons` — a deployed `SetClaimManager` per project/season, so `/claim/sign`
  can bind the attestation to the correct on-chain season contract.
- `claim_nonces` — single-use nonces issued to authorize on-chain claims; the row
  id is the nonce (globally unique => per-season unique).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("manager_address", sa.Text(), nullable=False, unique=True),
        sa.Column("atlas_hash", sa.Text(), nullable=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_seasons_contract", "seasons", ["contract_address"])

    op.create_table(
        "claim_nonces",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("wallet_address", sa.Text(), nullable=False),
        sa.Column("manager_address", sa.Text(), nullable=False),
        sa.Column("expiry", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("claim_nonces")
    op.drop_index("ix_seasons_contract", table_name="seasons")
    op.drop_table("seasons")
