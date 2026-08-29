"""Prevent concurrent duplicate active calls."""
from alembic import op
import sqlalchemy as sa

revision = "0002_active_call_integrity"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_index("uq_calls_active_token", "calls", ["token_id"], unique=True, postgresql_where=sa.text("status = 'ACTIVE'"))

def downgrade():
    op.drop_index("uq_calls_active_token", table_name="calls")
