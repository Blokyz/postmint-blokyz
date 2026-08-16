"""tokens.image_url — token artwork URL captured at ingest

Revision ID: 010
Revises: 009
Create Date: 2026-08-15

The standings Tiers-tab gallery shows the NFTs that qualify for each tier.
Moralis already returns each token's metadata during ingestion; this column
caches its image reference (http(s)/ipfs/data URI). NULL = metadata had no
image (or the row predates this column — re-ingest to backfill).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tokens", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tokens", "image_url")
