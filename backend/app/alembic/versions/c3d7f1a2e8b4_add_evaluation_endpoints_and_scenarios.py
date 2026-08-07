"""Add managed evaluation endpoints and multi-turn scenarios.

Revision ID: c3d7f1a2e8b4
Revises: b4e5d6f7a8b9
"""

import sqlalchemy as sa
from alembic import op


revision = "c3d7f1a2e8b4"
down_revision = "b4e5d6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluationendpoint",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("encrypted_headers", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("evaluationdataset", sa.Column("endpoint_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_evaluationdataset_endpoint_id",
        "evaluationdataset",
        "evaluationendpoint",
        ["endpoint_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("evaluationrun", sa.Column("baseline_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_evaluationrun_baseline_run_id",
        "evaluationrun",
        "evaluationrun",
        ["baseline_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "evaluationscenario",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["endpoint_id"], ["evaluationendpoint.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "evaluationscenarioturn",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("encrypted_headers", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("response_path", sa.String(length=500), nullable=True),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["scenario_id"], ["evaluationscenario.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario_id", "identifier", name="uq_scenario_turn_identifier"),
    )
    op.create_table(
        "evaluationscenariorun",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("average_score", sa.Float(), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scenario_id"], ["evaluationscenario.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "evaluationscenariorunturn",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_turn_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("identifier", sa.String(length=100), nullable=False),
        sa.Column("request_body", sa.Text(), nullable=False),
        sa.Column("actual_output", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["evaluationscenariorun.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_turn_id"], ["evaluationscenarioturn.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("evaluationscenariorunturn")
    op.drop_table("evaluationscenariorun")
    op.drop_table("evaluationscenarioturn")
    op.drop_table("evaluationscenario")
    op.drop_constraint("fk_evaluationrun_baseline_run_id", "evaluationrun", type_="foreignkey")
    op.drop_column("evaluationrun", "baseline_run_id")
    op.drop_constraint("fk_evaluationdataset_endpoint_id", "evaluationdataset", type_="foreignkey")
    op.drop_column("evaluationdataset", "endpoint_id")
    op.drop_table("evaluationendpoint")
