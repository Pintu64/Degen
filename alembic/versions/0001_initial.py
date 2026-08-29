"""Initial scanner schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

money = sa.Numeric(38, 18)
multiple = sa.Numeric(20, 8)


def upgrade():
    op.create_table("tokens", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("chain", sa.String(16), nullable=False), sa.Column("contract_address", sa.String(128), nullable=False), sa.Column("name", sa.String(255)), sa.Column("symbol", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("chain", "contract_address", name="uq_token_chain_address"))
    op.create_index("ix_tokens_chain", "tokens", ["chain"])
    op.create_table("calls", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("token_id", sa.BigInteger(), sa.ForeignKey("tokens.id"), nullable=False), sa.Column("reference_price", money, nullable=False), sa.Column("reference_timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("initial_market_cap", money), sa.Column("initial_liquidity", money), sa.Column("initial_volume", money), sa.Column("initial_score", sa.Integer(), nullable=False), sa.Column("initial_risk", sa.String(32), nullable=False), sa.Column("initial_snapshot", sa.JSON(), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("current_price", money, nullable=False), sa.Column("current_multiple", multiple, nullable=False), sa.Column("highest_price", money, nullable=False), sa.Column("highest_multiple", multiple, nullable=False), sa.Column("highest_timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("alert_message_id", sa.BigInteger()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_calls_token_id", "calls", ["token_id"]); op.create_index("ix_calls_status", "calls", ["status"])
    op.create_table("milestones", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("call_id", sa.BigInteger(), sa.ForeignKey("calls.id"), nullable=False), sa.Column("target_multiple", multiple, nullable=False), sa.Column("target_price", money, nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("hit_price", money), sa.Column("hit_timestamp", sa.DateTime(timezone=True)), sa.Column("telegram_message_id", sa.BigInteger()), sa.UniqueConstraint("call_id", "target_multiple", name="uq_call_milestone"))
    op.create_index("ix_milestones_call_id", "milestones", ["call_id"]); op.create_index("ix_milestones_status", "milestones", ["status"])
    op.create_table("price_snapshots", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("call_id", sa.BigInteger(), sa.ForeignKey("calls.id"), nullable=False), sa.Column("price", money, nullable=False), sa.Column("multiple", multiple, nullable=False), sa.Column("market_cap", money), sa.Column("liquidity", money), sa.Column("volume", money), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("provider", sa.String(64), nullable=False))
    op.create_index("ix_price_snapshots_call_id", "price_snapshots", ["call_id"]); op.create_index("ix_price_snapshots_timestamp", "price_snapshots", ["timestamp"]); op.create_index("ix_price_snapshots_call_timestamp", "price_snapshots", ["call_id", "timestamp"])
    op.create_table("token_snapshots", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("token_id", sa.BigInteger(), sa.ForeignKey("tokens.id"), nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("provider", sa.String(64), nullable=False), sa.Column("payload", sa.JSON(), nullable=False))
    op.create_index("ix_token_snapshots_token_id", "token_snapshots", ["token_id"]); op.create_index("ix_token_snapshots_timestamp", "token_snapshots", ["timestamp"])
    op.create_table("audit_corrections", sa.Column("id", sa.BigInteger(), primary_key=True), sa.Column("call_id", sa.BigInteger(), sa.ForeignKey("calls.id"), nullable=False), sa.Column("field_name", sa.String(64), nullable=False), sa.Column("old_value", sa.Text(), nullable=False), sa.Column("proposed_value", sa.Text(), nullable=False), sa.Column("reason", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_audit_corrections_call_id", "audit_corrections", ["call_id"])


def downgrade():
    for table in ("audit_corrections", "token_snapshots", "price_snapshots", "milestones", "calls", "tokens"):
        op.drop_table(table)
