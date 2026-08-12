"""Persist per-case single-turn request and extraction configuration.

Revision ID: f5c8d0e2a4b6
Revises: e4b7c9d1f3a5
"""

import sqlalchemy as sa
from alembic import op

revision = "f5c8d0e2a4b6"
down_revision = "e4b7c9d1f3a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluationdatasetrow", sa.Column("request_headers", sa.JSON(), nullable=True)
    )
    op.add_column(
        "evaluationdatasetrow", sa.Column("request_body", sa.Text(), nullable=True)
    )
    op.add_column(
        "evaluationdatasetrow",
        sa.Column("response_path", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluationdatasetrow", "response_path")
    op.drop_column("evaluationdatasetrow", "request_body")
    op.drop_column("evaluationdatasetrow", "request_headers")
