"""Expand schedules to interval/cron and single/multi-turn targets.

Revision ID: a1f3c5e7b9d2
Revises: c7e9a2b4d6f8
"""

import sqlalchemy as sa
from alembic import op

revision = "a1f3c5e7b9d2"
down_revision = "c7e9a2b4d6f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluationschedule",
        sa.Column(
            "schedule_type",
            sa.String(length=16),
            nullable=False,
            server_default="interval",
        ),
    )
    op.add_column(
        "evaluationschedule", sa.Column("cron_expression", sa.String(100))
    )
    op.add_column(
        "evaluationschedule",
        sa.Column(
            "timezone",
            sa.String(length=100),
            nullable=False,
            server_default="Asia/Seoul",
        ),
    )
    op.add_column("evaluationschedule", sa.Column("scenario_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_evaluationschedule_scenario_id",
        "evaluationschedule",
        "evaluationscenario",
        ["scenario_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("evaluationschedule", "dataset_id", nullable=True)
    op.alter_column("evaluationschedule", "interval_seconds", nullable=True)
    op.drop_constraint(
        "ck_evaluation_schedule_interval", "evaluationschedule", type_="check"
    )
    op.create_check_constraint(
        "ck_evaluation_schedule_target",
        "evaluationschedule",
        "(dataset_id IS NOT NULL AND scenario_id IS NULL) OR "
        "(dataset_id IS NULL AND scenario_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_evaluation_schedule_mode",
        "evaluationschedule",
        "(schedule_type = 'interval' AND interval_seconds BETWEEN 60 AND 31536000 "
        "AND cron_expression IS NULL) OR "
        "(schedule_type = 'cron' AND interval_seconds IS NULL "
        "AND cron_expression IS NOT NULL)",
    )

    op.add_column("evaluationjob", sa.Column("scenario_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_evaluationjob_scenario_id",
        "evaluationjob",
        "evaluationscenario",
        ["scenario_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("evaluationjob", "dataset_id", nullable=True)
    op.create_check_constraint(
        "ck_evaluation_job_target",
        "evaluationjob",
        "(dataset_id IS NOT NULL AND scenario_id IS NULL) OR "
        "(dataset_id IS NULL AND scenario_id IS NOT NULL)",
    )

    op.add_column("evaluationscenariorun", sa.Column("job_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_evaluationscenariorun_job_id",
        "evaluationscenariorun",
        "evaluationjob",
        ["job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_evaluationscenariorun_job_id", "evaluationscenariorun", ["job_id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_evaluationscenariorun_job_id", "evaluationscenariorun", type_="unique"
    )
    op.drop_constraint(
        "fk_evaluationscenariorun_job_id", "evaluationscenariorun", type_="foreignkey"
    )
    op.drop_column("evaluationscenariorun", "job_id")

    op.execute("DELETE FROM evaluationjob WHERE scenario_id IS NOT NULL")
    op.drop_constraint("ck_evaluation_job_target", "evaluationjob", type_="check")
    op.drop_constraint(
        "fk_evaluationjob_scenario_id", "evaluationjob", type_="foreignkey"
    )
    op.drop_column("evaluationjob", "scenario_id")
    op.alter_column("evaluationjob", "dataset_id", nullable=False)

    op.execute("DELETE FROM evaluationschedule WHERE scenario_id IS NOT NULL")
    op.drop_constraint(
        "ck_evaluation_schedule_mode", "evaluationschedule", type_="check"
    )
    op.drop_constraint(
        "ck_evaluation_schedule_target", "evaluationschedule", type_="check"
    )
    op.execute("DELETE FROM evaluationschedule WHERE schedule_type = 'cron'")
    op.alter_column("evaluationschedule", "interval_seconds", nullable=False)
    op.alter_column("evaluationschedule", "dataset_id", nullable=False)
    op.create_check_constraint(
        "ck_evaluation_schedule_interval",
        "evaluationschedule",
        "interval_seconds >= 60 AND interval_seconds <= 31536000",
    )
    op.drop_constraint(
        "fk_evaluationschedule_scenario_id",
        "evaluationschedule",
        type_="foreignkey",
    )
    op.drop_column("evaluationschedule", "scenario_id")
    op.drop_column("evaluationschedule", "timezone")
    op.drop_column("evaluationschedule", "cron_expression")
    op.drop_column("evaluationschedule", "schedule_type")
