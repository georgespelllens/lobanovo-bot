"""Add miniapp columns to users table.

Revision ID: 002_miniapp
Revises: 001_initial
Create Date: 2026-02-10
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "002_miniapp"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("miniapp_token_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("miniapp_last_seen", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "miniapp_last_seen")
    op.drop_column("users", "miniapp_token_hash")
