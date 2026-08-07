"""tokens.acquired_at — when the current owner received each token

Revision ID: 008
Revises: 007
Create Date: 2026-08-04

Holding windows are now derived from on-chain acquisition history instead of an
explicit START CLOCK opt-in: the window for a tier starts when the wallet
acquired its X-th qualifying token. This column caches the Transfer-event block
timestamp per token; NULL means "unknown" and triggers the lazy per-wallet
Moralis backfill (claims/acquisitions.py).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tokens", sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tokens", "acquired_at")
