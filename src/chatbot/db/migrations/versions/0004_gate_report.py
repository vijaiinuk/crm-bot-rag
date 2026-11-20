"""Publish gate results on each index version (S2.4.1).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-20
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE index_versions
            ADD COLUMN gate_report jsonb,   -- the gate's full result; promote requires passed
            ADD COLUMN gated_at timestamptz;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE index_versions DROP COLUMN gate_report, DROP COLUMN gated_at")
