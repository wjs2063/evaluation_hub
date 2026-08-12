"""Allow datasets to use only an administrator-managed endpoint reference.

Revision ID: a6d9e1f3b5c7
Revises: f5c8d0e2a4b6
"""

from alembic import op

revision = "a6d9e1f3b5c7"
down_revision = "f5c8d0e2a4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("evaluationdataset", "endpoint_url", nullable=True)


def downgrade() -> None:
    # Rows created with managed endpoint_id values may intentionally have no
    # legacy endpoint_url, so a safe downgrade must backfill before NOT NULL.
    op.execute(
        "UPDATE evaluationdataset d SET endpoint_url = e.base_url "
        "FROM evaluationendpoint e "
        "WHERE d.endpoint_url IS NULL AND d.endpoint_id = e.id"
    )
    op.alter_column("evaluationdataset", "endpoint_url", nullable=False)
