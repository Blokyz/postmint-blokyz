"""ingest_jobs: unique active job per contract (Wave 3)

Revision ID: 004
Revises: 003
Create Date: 2026-07-06

Partial unique index enforcing at most one active (not failed/complete) job
per contract, closing the /ingest check-then-insert race. Pre-existing
duplicate active jobs (stale rows from crashed runs) are failed first, keeping
only the most recent per contract, so index creation cannot collide.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ingest_jobs
        SET status = 'failed',
            phase = 'failed',
            error_message = COALESCE(
                error_message,
                'Superseded stale duplicate active job (Wave 3 unique-active-job migration).'
            )
        WHERE status NOT IN ('failed', 'complete')
          AND id NOT IN (
              SELECT DISTINCT ON (contract_address) id
              FROM ingest_jobs
              WHERE status NOT IN ('failed', 'complete')
              ORDER BY contract_address, created_at DESC
          )
        """
    )
    op.create_index(
        "uix_ingest_jobs_one_active_per_contract",
        "ingest_jobs",
        ["contract_address"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('failed', 'complete')"),
    )


def downgrade() -> None:
    op.drop_index("uix_ingest_jobs_one_active_per_contract", table_name="ingest_jobs")
