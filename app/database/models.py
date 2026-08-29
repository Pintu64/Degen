from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


MONEY = Numeric(38, 18)
MULTIPLE = Numeric(20, 8)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Token(Base, TimestampMixin):
    __tablename__ = "tokens"
    __table_args__ = (UniqueConstraint("chain", "contract_address", name="uq_token_chain_address"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chain: Mapped[str] = mapped_column(String(16), index=True)
    contract_address: Mapped[str] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(String(255))
    symbol: Mapped[str | None] = mapped_column(String(64))
    calls: Mapped[list["Call"]] = relationship(back_populates="token")


class Call(Base, TimestampMixin):
    __tablename__ = "calls"
    __table_args__ = (
        Index("uq_calls_active_token", "token_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"), index=True)
    reference_price: Mapped[Decimal] = mapped_column(MONEY)
    reference_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    initial_market_cap: Mapped[Decimal | None] = mapped_column(MONEY)
    initial_liquidity: Mapped[Decimal | None] = mapped_column(MONEY)
    initial_volume: Mapped[Decimal | None] = mapped_column(MONEY)
    initial_score: Mapped[int] = mapped_column(Integer)
    initial_risk: Mapped[str] = mapped_column(String(32))
    initial_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    current_price: Mapped[Decimal] = mapped_column(MONEY)
    current_multiple: Mapped[Decimal] = mapped_column(MULTIPLE, default=Decimal("1"))
    highest_price: Mapped[Decimal] = mapped_column(MONEY)
    highest_multiple: Mapped[Decimal] = mapped_column(MULTIPLE, default=Decimal("1"))
    highest_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    alert_message_id: Mapped[int | None] = mapped_column(BigInteger)
    token: Mapped[Token] = relationship(back_populates="calls")
    milestones: Mapped[list["Milestone"]] = relationship(back_populates="call", cascade="all, delete-orphan")


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (UniqueConstraint("call_id", "target_multiple", name="uq_call_milestone"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), index=True)
    target_multiple: Mapped[Decimal] = mapped_column(MULTIPLE)
    target_price: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    hit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    hit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    call: Mapped[Call] = relationship(back_populates="milestones")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    __table_args__ = (Index("ix_price_snapshots_call_timestamp", "call_id", "timestamp"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), index=True)
    price: Mapped[Decimal] = mapped_column(MONEY)
    multiple: Mapped[Decimal] = mapped_column(MULTIPLE)
    market_cap: Mapped[Decimal | None] = mapped_column(MONEY)
    liquidity: Mapped[Decimal | None] = mapped_column(MONEY)
    volume: Mapped[Decimal | None] = mapped_column(MONEY)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str] = mapped_column(String(64))


class TokenSnapshotRecord(Base):
    __tablename__ = "token_snapshots"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditCorrection(Base):
    __tablename__ = "audit_corrections"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str] = mapped_column(Text)
    proposed_value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
