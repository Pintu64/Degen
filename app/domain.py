from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Chain(StrEnum):
    SOLANA = "solana"
    ETHEREUM = "ethereum"
    BSC = "bsc"
    BASE = "base"

    @property
    def is_evm(self) -> bool:
        return self in {Chain.ETHEREUM, Chain.BSC, Chain.BASE}


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
    volume_m5: Decimal | None = None
    volume_1h: Decimal | None = None
    volume_6h: Decimal | None = None
    volume_24h: Decimal | None = None
    price_change_m5: Decimal | None = None
    price_change_1h: Decimal | None = None
    price_change_6h: Decimal | None = None
    price_change_24h: Decimal | None = None
    buys: int | None = None
    sells: int | None = None
    buys_m5: int | None = None
    sells_m5: int | None = None
    transactions: int | None = None
    boosted: bool = False
    holders: int | None = None
    top_holder_percentage: Decimal | None = None
    token_age_seconds: int | None = None
    pair_age_seconds: int | None = None
    dex: str | None = None
    pair_address: str | None = None
    quote_symbol: str | None = None
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
        return cleaned.lower() if isinstance(chain, Chain) and chain.is_evm else cleaned


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


class CoinScan(BaseModel):
    honeypot: bool | None = None
    mint_authority: bool | None = None
    freeze_authority: bool | None = None
    ownership_renounced: bool | None = None
    buy_tax: Decimal | None = None
    sell_tax: Decimal | None = None
    holders: int | None = None
    top10_percent: Decimal | None = None
    lp_locked: bool | None = None
    lp_locked_percent: Decimal | None = None
    verified: bool | None = None
    proxy: bool | None = None
    blacklist: bool | None = None
    rugged: bool | None = None
    source: str = "none"
    safety_score: int | None = None
    checks: dict[str, str] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    fatal: bool = False
    top_holders: list[dict] = Field(default_factory=list)


class RiskVerdict(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARN = "PASS_WITH_WARN"
    FAIL = "FAIL"
    UNSCANNED = "UNSCANNED"


class RiskCheck(BaseModel):
    name: str
    result: str
    evidence: str = ""
    critical: bool = False


class DeepRiskReport(BaseModel):
    verdict: RiskVerdict = RiskVerdict.UNSCANNED
    checks: list[RiskCheck] = Field(default_factory=list)
    critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)


class CandidateAnalysis(BaseModel):
    snapshot: TokenSnapshot
    filters: FilterResult
    risk: RiskAssessment
    score: ScoreResult
    ai_summary: str | None = None
    data_conflict: bool = False
    degen_score: int = Field(0, ge=0, le=100)
    degen_reasons: list[str] = Field(default_factory=list)
    too_late: bool = False
    coin_scan: CoinScan | None = None
    deep_risk: DeepRiskReport | None = None
    alpha: dict[str, int] = Field(default_factory=dict)
