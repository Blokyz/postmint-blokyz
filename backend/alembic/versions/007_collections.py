"""collections table — slug -> contract registry for the holder app (Phase 1)

Revision ID: 007
Revises: 006
Create Date: 2026-07-16

Maps a URL-safe `slug` to a collection contract so the public holder app can be
routed by `/c/{slug}`. One row per contract (unique), created at the operator's
"Publish" step.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("contract_address", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("chain", sa.Text(), nullable=False, server_default="eth"),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("collections")
