"""Add creator and last editor audit fields to evaluation datasets.

Revision ID: e4b7c9d1f3a5
Revises: a1f3c5e7b9d2
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b7c9d1f3a5"
down_revision = "a1f3c5e7b9d2"
branch_labels = None
depends_on = None


def _add_audit_columns(table_name: str) -> None:
    op.add_column(table_name, sa.Column("created_by_id", sa.Uuid(), nullable=True))
    op.add_column(table_name, sa.Column("updated_by_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            f'UPDATE "{table_name}" SET created_by_id = owner_id, '
            "updated_by_id = owner_id"
        )
    )
    op.create_foreign_key(
        f"fk_{table_name}_created_by_id",
        table_name,
        "user",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        f"fk_{table_name}_updated_by_id",
        table_name,
        "user",
        ["updated_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def upgrade() -> None:
    _add_audit_columns("evaluationdataset")
    _add_audit_columns("evaluationscenario")


def downgrade() -> None:
    for table_name in ("evaluationscenario", "evaluationdataset"):
        op.drop_constraint(
            f"fk_{table_name}_updated_by_id", table_name, type_="foreignkey"
        )
        op.drop_constraint(
            f"fk_{table_name}_created_by_id", table_name, type_="foreignkey"
        )
        op.drop_column(table_name, "updated_by_id")
        op.drop_column(table_name, "created_by_id")
