"""claims windows: transfer_sync table + one-active-window index (Phase 3)

Revision ID: 005
Revises: 004
Create Date: 2026-07-13

Holding-window engine support:
- `transfer_sync` — resumable high-water block per contract for the transfer poller.
- Partial unique index on `claims`: at most one active (not-yet-won) window per
  (contract, tier, wallet). A wallet may still start a fresh window for another
  slot after winning one (won rows have on_chain_tx_hash set and are excluded),
  preserving the no-whale-cap rule.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transfer_sync",
        sa.Column("contract_address", sa.Text(), primary_key=True),
        sa.Column("last_block", sa.BigInteger(), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "uix_claims_one_active_window",
        "claims",
        ["contract_address", "tier", "wallet_address"],
        unique=True,
        postgresql_where=sa.text("on_chain_tx_hash IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uix_claims_one_active_window", table_name="claims")
    op.drop_table("transfer_sync")
