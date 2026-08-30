from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_env: str = "production"
    service_role: str = "bot"
    telegram_bot_token: str = ""
    owner_telegram_id: int = Field(0, ge=0)
    database_url: str = "postgresql+asyncpg://scanner:scanner@postgres:5432/scanner"
    redis_url: str = "redis://redis:6379/0"
    dexscreener_base_url: str = "https://api.dexscreener.com"
    solana_api_key: str | None = None
    ethereum_api_key: str | None = None
    bsc_api_key: str | None = None
    base_api_key: str | None = None
    fluxrpc_api_key: str | None = None
    fluxrpc_url: str | None = None
    flux_shield_url: str | None = None
    birdeye_api_key: str | None = None
    birdeye_base_url: str = "https://public-api.birdeye.so"
    ai_enabled: bool = True
    ai_api_key: str | None = None
    ai_base_url: str = "https://agentrouter.org/v1"
    ai_model: str = "glm-5.3"
    ai_timeout_seconds: int = Field(15, ge=1, le=60)
    ai_failure_cooldown_seconds: int = Field(900, ge=30)
    tracking_interval_seconds: int = Field(10, ge=5)
    scan_interval_seconds: int = Field(8, ge=5)
    snapshot_retention_days: int = Field(30, ge=1)
    min_liquidity_usd: Decimal = Field(Decimal("5000"), ge=0)
    min_volume_24h_usd: Decimal = Field(Decimal("3000"), ge=0)
    min_txns_24h: int = Field(20, ge=0)
    min_score: int = Field(78, ge=0, le=100)
    warn_call_score: int = Field(85, ge=0, le=100)
    max_top_holder_percent: Decimal = Field(Decimal("35"), ge=0, le=100)
    min_data_quality: Decimal = Field(Decimal("0.55"), ge=0, le=1)
    max_data_age_seconds: int = Field(180, ge=1)
    max_provider_price_deviation_percent: Decimal = Field(Decimal("25"), ge=0)
    max_price_jump_multiple: Decimal = Field(Decimal("100"), gt=1)
    token_cooldown_seconds: int = Field(21600, ge=1)
    alert_cooldown_seconds: int = Field(60, ge=1)
    minimum_score_change: int = Field(5, ge=0, le=100)
    watch_score: int = Field(60, ge=0, le=100)
    interesting_score: int = Field(70, ge=0, le=100)
    strong_score: int = Field(80, ge=0, le=100)
    extreme_score: int = Field(90, ge=0, le=100)
    default_milestones: Annotated[tuple[Decimal, ...], NoDecode] = (
        Decimal("1.25"), Decimal("1.5"), Decimal("2"), Decimal("3"),
        Decimal("5"), Decimal("10"), Decimal("20"), Decimal("50"),
    )
    enabled_chains: Annotated[tuple[str, ...], NoDecode] = ("solana", "ethereum", "bsc", "base")
    max_degen_picks: int = Field(1, ge=1, le=4)
    max_degen_alerts_per_cycle: int = Field(1, ge=1, le=2)
    max_degen_market_cap_usd: Decimal = Field(Decimal("220000"), ge=0)
    max_degen_liquidity_usd: Decimal = Field(Decimal("90000"), ge=0)
    max_degen_24h_change_percent: Decimal = Field(Decimal("250"), ge=0)
    min_degen_pair_age_seconds: int = Field(60, ge=0)
    max_degen_pair_age_seconds: int = Field(86400, ge=60)
    preferred_degen_pair_age_seconds: int = Field(4500, ge=60)
    official_call_gap_seconds: int = Field(600, ge=60)
    nuke_score: int = Field(90, ge=80, le=100)
    close_score_delta: int = Field(2, ge=0, le=20)
    log_level: str = "INFO"
    web_port: int = 8080

    @field_validator("default_milestones", "enabled_chains", mode="before")
    @classmethod
    def parse_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("default_milestones")
    @classmethod
    def validate_milestones(cls, value: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
        if not value or any(item <= 1 or not item.is_finite() for item in value):
            raise ValueError("DEFAULT_MILESTONES must contain finite values greater than 1")
        if len(set(value)) != len(value):
            raise ValueError("DEFAULT_MILESTONES must not contain duplicates")
        return tuple(sorted(value))

    @field_validator("enabled_chains")
    @classmethod
    def validate_chains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.lower() for item in value)
        if not normalized:
            raise ValueError("ENABLED_CHAINS must contain at least one chain")
        invalid = set(normalized) - {"solana", "ethereum", "bsc", "base"}
        if invalid:
            raise ValueError(f"Unsupported chains: {', '.join(sorted(invalid))}")
        return normalized

    @model_validator(mode="after")
    def validate_score_thresholds(self):
        thresholds = (self.watch_score, self.interesting_score, self.strong_score, self.extreme_score)
        if thresholds != tuple(sorted(thresholds)) or any(x < 0 or x > 100 for x in thresholds):
            raise ValueError("Alert score thresholds must be ordered and between 0 and 100")
        return self

    @field_validator("database_url")
    @classmethod
    def async_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must use redis:// or rediss://")
        return value

    def validate_runtime(self, role: str) -> None:
        if role in {"bot", "telegram"} and (not self.telegram_bot_token or self.owner_telegram_id <= 0):
            raise ValueError("TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID are required for the bot service")


@lru_cache
def get_settings() -> Settings:
    return Settings()
