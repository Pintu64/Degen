"""Track official vs personal paper calls."""
from alembic import op
import sqlalchemy as sa

revision = "0003_call_source"
down_revision = "0002_active_call_integrity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calls", sa.Column("source", sa.String(16), nullable=False, server_default="OFFICIAL"))
    op.create_index("ix_calls_source", "calls", ["source"])


def downgrade():
    op.drop_index("ix_calls_source", table_name="calls")
    op.drop_column("calls", "source")
