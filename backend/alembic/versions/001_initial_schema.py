"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-05-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tokens",
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=False),
        sa.Column("owner_address", sa.Text(), nullable=True),
        sa.Column("snapshot_block", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("contract_address", "token_id"),
    )
    op.create_table(
        "traits",
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=False),
        sa.Column("trait_category", sa.Text(), nullable=False),
        sa.Column("trait_value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("contract_address", "token_id", "trait_category"),
    )
    op.create_table(
        "sales",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=False),
        sa.Column("sale_price_eth", sa.Numeric(18, 8), nullable=False),
        sa.Column("seller_address", sa.Text(), nullable=True),
        sa.Column("buyer_address", sa.Text(), nullable=True),
        sa.Column("marketplace", sa.Text(), nullable=True),
        sa.Column("tx_hash", sa.Text(), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wash_trade_flag", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash"),
    )
    op.create_index("ix_sales_contract_address", "sales", ["contract_address"])
    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("wallet_address", sa.Text(), nullable=False),
        sa.Column("window_started", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_completed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slot_number", sa.Integer(), nullable=True),
        sa.Column("qualifying_tokens", sa.ARRAY(sa.Integer()), nullable=True),
        sa.Column("on_chain_tx_hash", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_address", "tier", "wallet_address"),
    )
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress_pct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingest_jobs_contract_address", "ingest_jobs", ["contract_address"])


def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_contract_address", table_name="ingest_jobs")
    op.drop_table("ingest_jobs")
    op.drop_table("claims")
    op.drop_index("ix_sales_contract_address", table_name="sales")
    op.drop_table("sales")
    op.drop_table("traits")
    op.drop_table("tokens")
