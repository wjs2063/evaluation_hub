"""Add evaluation datasets and saved execution runs.

Revision ID: b4e5d6f7a8b9
Revises: fe56fa70289e
"""

import sqlalchemy as sa
from alembic import op


revision = "b4e5d6f7a8b9"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluationdataset",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("evaluation_type", sa.String(length=32), nullable=False),
        sa.Column("endpoint_url", sa.String(length=2048), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("headers", sa.JSON(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("response_path", sa.String(length=500), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "evaluationdatasetrow",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluationdataset.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "evaluationrun",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("evaluator", sa.String(length=100), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("average_score", sa.Float(), nullable=False),
        sa.Column("geval_available", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluationdataset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "evaluationrunrow",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_row_id", sa.Uuid(), nullable=True),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.Column("actual_output", sa.Text(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["evaluationrun.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_row_id"], ["evaluationdatasetrow.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("evaluationrunrow")
    op.drop_table("evaluationrun")
    op.drop_table("evaluationdatasetrow")
    op.drop_table("evaluationdataset")
