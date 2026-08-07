"""Add DeepEval evaluator configuration and conversation results.

Revision ID: d6e8a5f9b3c1
Revises: c3d7f1a2e8b4
"""

import sqlalchemy as sa
from alembic import op


revision = "d6e8a5f9b3c1"
down_revision = "c3d7f1a2e8b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluationdataset",
        sa.Column("evaluator", sa.String(length=32), nullable=False, server_default="deepeval"),
    )
    op.add_column(
        "evaluationscenario",
        sa.Column("evaluator", sa.String(length=32), nullable=False, server_default="deepeval"),
    )
    op.add_column(
        "evaluationscenariorun",
        sa.Column("evaluator", sa.String(length=32), nullable=False, server_default="deepeval"),
    )
    op.add_column("evaluationscenariorun", sa.Column("geval_score", sa.Float(), nullable=True))
    op.add_column("evaluationscenariorun", sa.Column("geval_reason", sa.Text(), nullable=True))
    op.alter_column("evaluationdataset", "evaluator", server_default=None)
    op.alter_column("evaluationscenario", "evaluator", server_default=None)
    op.alter_column("evaluationscenariorun", "evaluator", server_default=None)


def downgrade() -> None:
    op.drop_column("evaluationscenariorun", "geval_reason")
    op.drop_column("evaluationscenariorun", "geval_score")
    op.drop_column("evaluationscenariorun", "evaluator")
    op.drop_column("evaluationscenario", "evaluator")
    op.drop_column("evaluationdataset", "evaluator")
