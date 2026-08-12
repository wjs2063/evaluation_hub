"""Lock metric profiles to the supported DeepEval catalog.

Revision ID: b4d8f1a6c2e7
Revises: a9c4e7f2b6d1
"""

import sqlalchemy as sa
from alembic import op

revision = "b4d8f1a6c2e7"
down_revision = "a9c4e7f2b6d1"
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
)


def upgrade() -> None:
    allowed = ", ".join(f"'{metric}'" for metric in SUPPORTED_METRICS)
    op.create_check_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        f"key IN ({allowed})",
    )
    op.add_column(
        "evaluationrunmetricresult",
        sa.Column("raw_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "evaluationrunmetricresult",
        sa.Column(
            "score_direction",
            sa.String(length=32),
            nullable=False,
            server_default="higher_is_better",
        ),
    )


def downgrade() -> None:
    op.drop_column("evaluationrunmetricresult", "score_direction")
    op.drop_column("evaluationrunmetricresult", "raw_score")
    op.drop_constraint(
        "ck_metric_profile_item_supported_key",
        "evaluationmetricprofileitem",
        type_="check",
    )
