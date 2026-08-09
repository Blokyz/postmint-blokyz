"""manifests table — ranking + atlas manifests stored in Postgres, not on disk

Revision ID: 009
Revises: 008
Create Date: 2026-08-09

Manifests used to be JSON files under backend/output. On a container host
(Render) the filesystem is ephemeral (wiped on deploy) and not shared between
the API and the Celery worker, so approved/generated manifests would vanish or
diverge. This moves them into a table keyed by (contract_address, kind) —
kind in ('ranking','atlas') — with the exact manifest dict as JSONB.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "manifests",
        sa.Column("contract_address", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("contract_address", "kind"),
    )


def downgrade() -> None:
    op.drop_table("manifests")
