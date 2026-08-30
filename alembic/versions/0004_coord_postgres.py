"""Postgres locks, heartbeats, and telegram queue (no Redis required)."""
from alembic import op
import sqlalchemy as sa

revision = "0004_coord_postgres"
down_revision = "0003_call_source"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "coord_kv",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_coord_kv_expires_at", "coord_kv", ["expires_at"])
    op.create_table(
        "coord_queue",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("queue", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_coord_queue_queue", "coord_queue", ["queue"])
    op.create_index("ix_coord_queue_status", "coord_queue", ["status"])


def downgrade():
    op.drop_table("coord_queue")
    op.drop_table("coord_kv")
