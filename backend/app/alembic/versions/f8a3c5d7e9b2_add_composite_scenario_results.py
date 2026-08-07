"""Add composite multi-turn evaluation results.

Revision ID: f8a3c5d7e9b2
Revises: e7f2a4c8d9b1
"""

import sqlalchemy as sa
from alembic import op

revision = "f8a3c5d7e9b2"
down_revision = "e7f2a4c8d9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluationscenariorun",
        sa.Column("turn_average_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "evaluationscenariorun",
        sa.Column("overall_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "evaluationscenariorun",
        sa.Column(
            "overall_passed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "evaluationscenariorun",
        sa.Column("overall_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "evaluationscenariorunturn",
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE evaluationscenariorun
            SET turn_average_score = average_score,
                overall_score = average_score,
                overall_passed = (total > 0 AND passed = total),
                overall_reason = '기존 실행 결과로, 턴별·대화 점수가 분리 저장되지 않았습니다.'
            """
        )
    )
    op.alter_column("evaluationscenariorun", "turn_average_score", server_default=None)
    op.alter_column("evaluationscenariorun", "overall_score", server_default=None)
    op.alter_column("evaluationscenariorun", "overall_passed", server_default=None)


def downgrade() -> None:
    op.drop_column("evaluationscenariorunturn", "reason")
    op.drop_column("evaluationscenariorun", "overall_reason")
    op.drop_column("evaluationscenariorun", "overall_passed")
    op.drop_column("evaluationscenariorun", "overall_score")
    op.drop_column("evaluationscenariorun", "turn_average_score")
