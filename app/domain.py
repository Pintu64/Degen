from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Chain(StrEnum):
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    BSC = "bsc"


class RiskLevel(StrEnum):
    LOWER = "LOWER RISK"
    MEDIUM = "MEDIUM RISK"
    HIGH = "HIGH RISK"
    UNKNOWN = "UNKNOWN"


class TokenSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chain: Chain
    contract_address: str = Field(min_length=2, max_length=128)
    name: str | None = None
    symbol: str | None = None
    decimals: int | None = None
    price: Decimal | None = None
    market_cap: Decimal | None = None
    fdv: Decimal | None = None
    liquidity: Decimal | None = None
    volume_1h: Decimal | None = None
    volume_6h: Decimal | None = None
    volume_24h: Decimal | None = None
    price_change_1h: Decimal | None = None
    price_change_6h: Decimal | None = None
    price_change_24h: Decimal | None = None
    buys: int | None = None
    sells: int | None = None
    transactions: int | None = None
    holders: int | None = None
    top_holder_percentage: Decimal | None = None
    token_age_seconds: int | None = None
    pair_age_seconds: int | None = None
    dex: str | None = None
    pair_address: str | None = None
    mint_authority: bool | None = None
    freeze_authority: bool | None = None
    contract_verified: bool | None = None
    ownership_renounced: bool | None = None
    buy_tax: Decimal | None = None
    sell_tax: Decimal | None = None
    suspicious_flags: list[str] = Field(default_factory=list)
    chart_url: HttpUrl | None = None
    explorer_url: HttpUrl | None = None
    website_url: HttpUrl | None = None
    social_urls: list[HttpUrl] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provider: str

    @field_validator("contract_address")
    @classmethod
    def normalize_address(cls, value: str, info):
        cleaned = value.strip()
        chain = info.data.get("chain")
        return cleaned.lower() if chain in {Chain.ETHEREUM, Chain.BSC} else cleaned


class FilterResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    data_quality: Decimal = Decimal("0")


class RiskAssessment(BaseModel):
    level: RiskLevel
    positive_signals: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    confidence: str
    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    coverage: Decimal = Decimal("0")


class CandidateAnalysis(BaseModel):
    snapshot: TokenSnapshot
    filters: FilterResult
    risk: RiskAssessment
    score: ScoreResult
    ai_summary: str | None = None
    data_conflict: bool = False
