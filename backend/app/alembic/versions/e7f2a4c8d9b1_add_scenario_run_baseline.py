"""Add baseline selection for multi-turn regression runs.

Revision ID: e7f2a4c8d9b1
Revises: d6e8a5f9b3c1
"""

import sqlalchemy as sa
from alembic import op


revision = "e7f2a4c8d9b1"
down_revision = "d6e8a5f9b3c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluationscenariorun",
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_evaluationscenariorun_baseline_run_id",
        "evaluationscenariorun",
        "evaluationscenariorun",
        ["baseline_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_evaluationscenariorun_baseline_run_id",
        "evaluationscenariorun",
        type_="foreignkey",
    )
    op.drop_column("evaluationscenariorun", "baseline_run_id")
