"""ingest_jobs: add phase column for phase-aware progress UI

Revision ID: 003
Revises: 0d2a7659f209
Create Date: 2026-06-29

Adds a coarse `phase` marker so the /ingest UI can show real stages
(fetching NFTs / sales / scoring) instead of a progress_pct that sits at 99
through the entire post-fetch analysis. progress_pct still tracks NFT paging.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "0d2a7659f209"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("phase", sa.Text(), nullable=False, server_default="queued"),
    )


def downgrade() -> None:
    op.drop_column("ingest_jobs", "phase")
