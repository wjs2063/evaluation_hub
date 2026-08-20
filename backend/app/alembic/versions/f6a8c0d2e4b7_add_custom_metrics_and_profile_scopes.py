"""Add shared custom metrics and screen-specific profile scopes.

Revision ID: f6a8c0d2e4b7
Revises: e3f5a7b9c1d2
"""

import sqlalchemy as sa
from alembic import op

revision = "f6a8c0d2e4b7"
down_revision = "e3f5a7b9c1d2"
branch_labels = None
depends_on = None

SUPPORTED_METRICS = (
    "geval_correctness",
    "geval_clarity",
    "geval_professionalism",
    "answer_relevancy",
    "summarization",
    "bias",
    "toxicity",
    "pii_leakage",
    "exact_match",
    "non_advice",
    "misuse",
    "role_violation",
    "turn_relevancy",
    "role_adherence",
    "knowledge_retention",
    "conversation_completeness",
)


def upgrade() -> None:
    op.create_table(
        "custommetric",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500)),
        sa.Column("evaluation_scope", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.String(length=8000), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.Uuid()),
        sa.Column("updated_by_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evaluation_scope IN ('quick_upload', 'single_turn', 'multi_turn')",
            name="ck_custom_metric_evaluation_scope",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "evaluationmetricprofile",
        sa.Column(
            "evaluation_scope",
            sa.String(length=32),
            nullable=False,
            server_default="single_turn",
        ),
    )
    op.execute("UPDATE evaluationmetricprofile SET evaluation_scope = evaluation_mode")
    op.create_check_constraint(
        "ck_metric_profile_evaluation_scope",
        "evaluationmetricprofile",
        "evaluation_scope IN ('quick_upload', 'single_turn', 'multi_turn')",
    )
    op.add_column(
        "evaluationmetricprofileitem", sa.Column("custom_metric_id", sa.Uuid())
    )
    op.add_column(
        "evaluationmetricprofileitem", sa.Column("custom_metric_version", sa.Integer())
    )
    op.add_column(
        "evaluationmetricprofileitem",
        sa.Column("custom_metric_prompt", sa.String(length=8000)),
    )
    op.add_column(
        "evaluationmetricprofileitem",
        sa.Column("custom_metric_scope", sa.String(length=32)),
    )
    op.add_column(
        "evaluationmetricprofileitem",
        sa.Column(
            "required_keys",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.create_foreign_key(
        "fk_metric_profile_item_custom_metric_id",
        "evaluationmetricprofileitem",
        "custommetric",
        ["custom_metric_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        type_="check",
    )
    op.create_check_constraint(
        "ck_metric_profile_item_identity",
        "evaluationmetricprofileitem",
        "(custom_metric_id IS NULL AND key NOT LIKE 'custom:%') OR "
        "(custom_metric_id IS NOT NULL AND key LIKE 'custom:%')",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM evaluationmetricprofile WHERE id IN "
        "(SELECT DISTINCT profile_id FROM evaluationmetricprofileitem "
        "WHERE custom_metric_id IS NOT NULL)"
    )
    op.drop_constraint(
        "ck_metric_profile_item_identity",
        "evaluationmetricprofileitem",
        type_="check",
    )
    allowed = ", ".join(f"'{metric}'" for metric in SUPPORTED_METRICS)
    op.create_check_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        f"key IN ({allowed})",
    )
    op.drop_constraint(
        "fk_metric_profile_item_custom_metric_id",
        "evaluationmetricprofileitem",
        type_="foreignkey",
    )
    op.drop_column("evaluationmetricprofileitem", "required_keys")
    op.drop_column("evaluationmetricprofileitem", "custom_metric_scope")
    op.drop_column("evaluationmetricprofileitem", "custom_metric_prompt")
    op.drop_column("evaluationmetricprofileitem", "custom_metric_version")
    op.drop_column("evaluationmetricprofileitem", "custom_metric_id")
    op.drop_constraint(
        "ck_metric_profile_evaluation_scope",
        "evaluationmetricprofile",
        type_="check",
    )
    op.drop_column("evaluationmetricprofile", "evaluation_scope")
    op.drop_table("custommetric")
