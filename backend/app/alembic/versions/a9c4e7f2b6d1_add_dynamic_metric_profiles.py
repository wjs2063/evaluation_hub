"""Add dynamic single-turn metric profiles and result evidence.

Revision ID: a9c4e7f2b6d1
Revises: f8a3c5d7e9b2
"""

import sqlalchemy as sa
from alembic import op

revision = "a9c4e7f2b6d1"
down_revision = "f8a3c5d7e9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluationmetricprofile",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluationmetricprofile_is_active",
        "evaluationmetricprofile",
        ["is_active"],
    )
    op.create_table(
        "evaluationmetricprofileitem",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("criteria", sa.String(length=2000), nullable=False),
        sa.Column("weight_percent", sa.Integer(), nullable=False),
        sa.Column("evaluation_params", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["evaluationmetricprofile.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id", "key", name="uq_metric_profile_item_key"
        ),
        sa.UniqueConstraint(
            "profile_id", "position", name="uq_metric_profile_item_position"
        ),
    )
    op.create_index(
        "ix_evaluationmetricprofileitem_profile_id",
        "evaluationmetricprofileitem",
        ["profile_id"],
    )
    op.add_column(
        "evaluationdataset", sa.Column("metric_profile_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_evaluationdataset_metric_profile_id",
        "evaluationdataset",
        "evaluationmetricprofile",
        ["metric_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "evaluationrun", sa.Column("metric_profile_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "evaluationrun", sa.Column("metric_profile_version", sa.Integer(), nullable=True)
    )
    op.add_column(
        "evaluationrun", sa.Column("metric_profile_snapshot", sa.JSON(), nullable=True)
    )
    op.create_foreign_key(
        "fk_evaluationrun_metric_profile_id",
        "evaluationrun",
        "evaluationmetricprofile",
        ["metric_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "evaluationrunmetricresult",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_row_id", sa.Uuid(), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("weight_percent", sa.Integer(), nullable=False),
        sa.Column("weighted_score", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=True),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_row_id"], ["evaluationrunrow.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_row_id", "metric_key", name="uq_run_metric_result_key"
        ),
    )
    op.create_index(
        "ix_evaluationrunmetricresult_run_row_id",
        "evaluationrunmetricresult",
        ["run_row_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluationrunmetricresult_run_row_id",
        table_name="evaluationrunmetricresult",
    )
    op.drop_table("evaluationrunmetricresult")
    op.drop_constraint(
        "fk_evaluationrun_metric_profile_id", "evaluationrun", type_="foreignkey"
    )
    op.drop_column("evaluationrun", "metric_profile_snapshot")
    op.drop_column("evaluationrun", "metric_profile_version")
    op.drop_column("evaluationrun", "metric_profile_id")
    op.drop_constraint(
        "fk_evaluationdataset_metric_profile_id",
        "evaluationdataset",
        type_="foreignkey",
    )
    op.drop_column("evaluationdataset", "metric_profile_id")
    op.drop_index(
        "ix_evaluationmetricprofileitem_profile_id",
        table_name="evaluationmetricprofileitem",
    )
    op.drop_table("evaluationmetricprofileitem")
    op.drop_index(
        "ix_evaluationmetricprofile_is_active",
        table_name="evaluationmetricprofile",
    )
    op.drop_table("evaluationmetricprofile")
