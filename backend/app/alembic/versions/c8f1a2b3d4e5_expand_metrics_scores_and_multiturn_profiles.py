"""Expand metric modes and migrate evaluation scores to 0-100.

Revision ID: c8f1a2b3d4e5
Revises: a6d9e1f3b5c7
"""

import sqlalchemy as sa
from alembic import op

revision = "c8f1a2b3d4e5"
down_revision = "a6d9e1f3b5c7"
branch_labels = None
depends_on = None

SCORE_COLUMNS = {
    "evaluationdataset": ("threshold",),
    "evaluationrun": ("average_score",),
    "evaluationrunrow": ("score",),
    "evaluationrunmetricresult": ("score", "weighted_score"),
    "evaluationscenario": ("threshold",),
    "evaluationscenariorun": (
        "turn_average_score",
        "overall_score",
        "average_score",
        "geval_score",
    ),
    "evaluationscenariorunturn": ("score",),
}

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
    op.execute(
        sa.text("""
        UPDATE evaluationscenarioturn
        SET url = COALESCE(NULLIF(regexp_replace(url, '^https?://[^/]+', ''), ''), '/')
        WHERE url ~ '^https?://'
    """)
    )
    op.drop_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        type_="check",
    )
    allowed = ", ".join(f"'{metric}'" for metric in SUPPORTED_METRICS)
    op.create_check_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        f"key IN ({allowed})",
    )
    op.add_column(
        "evaluationmetricprofile",
        sa.Column(
            "evaluation_mode",
            sa.String(length=32),
            nullable=False,
            server_default="single_turn",
        ),
    )
    op.add_column(
        "evaluationmetricprofileitem",
        sa.Column(
            "config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
    )
    op.add_column(
        "evaluationmetricprofileitem",
        sa.Column("custom_instruction", sa.String(length=2000)),
    )
    op.alter_column(
        "evaluationrunmetricresult", "raw_score", new_column_name="raw_score_ratio"
    )
    op.add_column("evaluationscenario", sa.Column("metric_profile_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_evaluationscenario_metric_profile_id",
        "evaluationscenario",
        "evaluationmetricprofile",
        ["metric_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "evaluationcomparison",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_mode", sa.String(length=32), nullable=False),
        sa.Column("dataset_id", sa.Uuid()),
        sa.Column("scenario_id", sa.Uuid()),
        sa.Column("endpoint_a_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_b_id", sa.Uuid(), nullable=False),
        sa.Column("metric_profile_id", sa.Uuid()),
        sa.Column("metric_profile_version", sa.Integer()),
        sa.Column("metric_profile_snapshot", sa.JSON()),
        sa.Column("comparison_mode", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="running"
        ),
        sa.Column("run_a_id", sa.Uuid()),
        sa.Column("run_b_id", sa.Uuid()),
        sa.Column("scenario_run_a_id", sa.Uuid()),
        sa.Column("scenario_run_b_id", sa.Uuid()),
        sa.Column("comparable_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winner_a_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winner_b_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tie_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "results", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["evaluationdataset.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["evaluationscenario.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_a_id"], ["evaluationendpoint.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["endpoint_b_id"], ["evaluationendpoint.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["metric_profile_id"], ["evaluationmetricprofile.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_a_id"], ["evaluationrun.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_b_id"], ["evaluationrun.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["scenario_run_a_id"], ["evaluationscenariorun.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["scenario_run_b_id"], ["evaluationscenariorun.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("evaluationrun", sa.Column("comparison_group_id", sa.Uuid()))
    op.add_column("evaluationscenariorun", sa.Column("comparison_group_id", sa.Uuid()))
    op.create_index(
        "ix_evaluationrun_comparison_group_id", "evaluationrun", ["comparison_group_id"]
    )
    op.create_index(
        "ix_evaluationscenariorun_comparison_group_id",
        "evaluationscenariorun",
        ["comparison_group_id"],
    )
    op.add_column("evaluationscenariorun", sa.Column("metric_profile_id", sa.Uuid()))
    op.add_column(
        "evaluationscenariorun", sa.Column("metric_profile_version", sa.Integer())
    )
    op.add_column(
        "evaluationscenariorun", sa.Column("metric_profile_snapshot", sa.JSON())
    )
    op.add_column(
        "evaluationscenariorun",
        sa.Column(
            "metrics", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
    )
    op.create_foreign_key(
        "fk_evaluationscenariorun_metric_profile_id",
        "evaluationscenariorun",
        "evaluationmetricprofile",
        ["metric_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )

    for table, columns in SCORE_COLUMNS.items():
        for column in columns:
            op.execute(
                sa.text(
                    f'UPDATE "{table}" SET "{column}" = "{column}" * 100 WHERE "{column}" IS NOT NULL'
                )
            )
            op.alter_column(
                table,
                column,
                existing_type=sa.Float(),
                type_=sa.Numeric(7, 3),
                postgresql_using=f'ROUND("{column}"::numeric, 3)',
            )

    # Preserve audit JSON while leaving the original DeepEval ratio untouched.
    op.execute(
        sa.text("""
        UPDATE evaluationrunrow
        SET metrics = COALESCE((
          SELECT json_agg(
            (metric::jsonb - 'score' - 'weighted_score' - 'raw_score') ||
            jsonb_build_object(
              'score', ROUND(((metric->>'score')::numeric * 100), 3),
              'weighted_score', ROUND(((metric->>'weighted_score')::numeric * 100), 3),
              'raw_score_ratio', COALESCE(metric->'raw_score_ratio', metric->'raw_score')
            )
          ) FROM json_array_elements(metrics) AS metric
        ), '[]'::json)
        WHERE json_typeof(metrics) = 'array' AND json_array_length(metrics) > 0
    """)
    )


def downgrade() -> None:
    for table, columns in SCORE_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.Numeric(7, 3),
                type_=sa.Float(),
                postgresql_using=f'("{column}"::double precision / 100.0)',
            )
    op.drop_index(
        "ix_evaluationscenariorun_comparison_group_id",
        table_name="evaluationscenariorun",
    )
    op.drop_index("ix_evaluationrun_comparison_group_id", table_name="evaluationrun")
    op.drop_column("evaluationscenariorun", "comparison_group_id")
    op.drop_column("evaluationrun", "comparison_group_id")
    op.drop_table("evaluationcomparison")
    op.drop_constraint(
        "fk_evaluationscenariorun_metric_profile_id",
        "evaluationscenariorun",
        type_="foreignkey",
    )
    for column in (
        "metrics",
        "metric_profile_snapshot",
        "metric_profile_version",
        "metric_profile_id",
    ):
        op.drop_column("evaluationscenariorun", column)
    op.drop_constraint(
        "fk_evaluationscenario_metric_profile_id",
        "evaluationscenario",
        type_="foreignkey",
    )
    op.drop_column("evaluationscenario", "metric_profile_id")
    op.alter_column(
        "evaluationrunmetricresult", "raw_score_ratio", new_column_name="raw_score"
    )
    op.drop_column("evaluationmetricprofileitem", "custom_instruction")
    op.drop_column("evaluationmetricprofileitem", "config")
    op.drop_column("evaluationmetricprofile", "evaluation_mode")
    op.drop_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        type_="check",
    )
    old = SUPPORTED_METRICS[:9]
    allowed = ", ".join(f"'{metric}'" for metric in old)
    op.create_check_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        f"key IN ({allowed})",
    )
