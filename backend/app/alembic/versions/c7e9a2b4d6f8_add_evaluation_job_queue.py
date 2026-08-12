"""Add scalable evaluation job queue and schedules.

Revision ID: c7e9a2b4d6f8
Revises: b4d8f1a6c2e7
"""

import sqlalchemy as sa
from alembic import op

revision = "c7e9a2b4d6f8"
down_revision = "b4d8f1a6c2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluationschedule",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "interval_seconds >= 60 AND interval_seconds <= 31536000",
            name="ck_evaluation_schedule_interval",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["evaluationdataset.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"], ["evaluationrun.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_schedule_due",
        "evaluationschedule",
        ["is_active", "next_run_at"],
    )
    op.create_table(
        "evaluationjob",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=True),
        sa.Column("schedule_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_evaluation_job_status",
        ),
        sa.CheckConstraint(
            "attempt >= 0 AND max_attempts >= 1 AND max_attempts <= 10",
            name="ck_evaluation_job_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["evaluationdataset.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["baseline_run_id"], ["evaluationrun.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["evaluationschedule.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "schedule_id", "scheduled_for", name="uq_evaluation_job_schedule_slot"
        ),
    )
    op.create_index(
        "ix_evaluation_job_claim",
        "evaluationjob",
        ["status", "available_at", "lease_expires_at", "created_at"],
    )
    op.create_index("ix_evaluation_job_owner", "evaluationjob", ["owner_id"])
    op.add_column("evaluationrun", sa.Column("job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_evaluationrun_job_id",
        "evaluationrun",
        "evaluationjob",
        ["job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_evaluationrun_job_id", "evaluationrun", ["job_id"])


def downgrade() -> None:
    op.drop_constraint("uq_evaluationrun_job_id", "evaluationrun", type_="unique")
    op.drop_constraint("fk_evaluationrun_job_id", "evaluationrun", type_="foreignkey")
    op.drop_column("evaluationrun", "job_id")
    op.drop_index("ix_evaluation_job_owner", table_name="evaluationjob")
    op.drop_index("ix_evaluation_job_claim", table_name="evaluationjob")
    op.drop_table("evaluationjob")
    op.drop_index("ix_evaluation_schedule_due", table_name="evaluationschedule")
    op.drop_table("evaluationschedule")
