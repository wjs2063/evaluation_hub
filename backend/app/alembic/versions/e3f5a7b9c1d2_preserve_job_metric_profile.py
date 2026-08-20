"""Preserve the run-specific metric profile on queued jobs.

Revision ID: e3f5a7b9c1d2
Revises: d2e4f6a8b0c1
"""

import sqlalchemy as sa
from alembic import op

revision = "e3f5a7b9c1d2"
down_revision = "d2e4f6a8b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluationjob", sa.Column("metric_profile_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_evaluationjob_metric_profile_id",
        "evaluationjob",
        "evaluationmetricprofile",
        ["metric_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("evaluationrunrow", "score", nullable=True)


def downgrade() -> None:
    op.execute("UPDATE evaluationrunrow SET score = 0 WHERE score IS NULL")
    op.alter_column("evaluationrunrow", "score", nullable=False)
    op.drop_constraint(
        "fk_evaluationjob_metric_profile_id", "evaluationjob", type_="foreignkey"
    )
    op.drop_column("evaluationjob", "metric_profile_id")
