from datetime import UTC, datetime
from decimal import Decimal
from app.config import Settings
from app.domain import Chain, RiskLevel, TokenSnapshot
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine
import pytest

def snapshot(**overrides):
    values=dict(chain=Chain.SOLANA,contract_address="abc",price=Decimal("1"),liquidity=Decimal("25000"),market_cap=Decimal("80000"),volume_24h=Decimal("100000"),transactions=200,buys=120,sells=80,buys_m5=30,sells_m5=10,price_change_m5=Decimal("4"),price_change_1h=Decimal("5"),price_change_6h=Decimal("10"),pair_age_seconds=900,timestamp=datetime.now(UTC),provider="test")
    values.update(overrides); return TokenSnapshot(**values)
def test_filter_passes_configured_thresholds(): assert FilterEngine(Settings()).evaluate(snapshot()).passed
def test_unknown_risk_when_authority_data_missing(): assert RiskAnalyzer().assess(snapshot()).level==RiskLevel.UNKNOWN
def test_score_confidence_reflects_missing_data():
    s=snapshot(); r=RiskAnalyzer().assess(s); result=ScoringEngine(Settings()).score(s,r); assert 0<=result.score<=100; assert result.confidence in {"Low","Medium","High"}

def test_config_rejects_duplicate_milestones():
    with pytest.raises(ValueError): Settings(default_milestones="2,2,3")

def test_config_rejects_unknown_chain():
    with pytest.raises(ValueError): Settings(enabled_chains="solana,unknown")

def test_config_accepts_base_chain():
    settings = Settings(_env_file=None, enabled_chains="solana,ethereum,bsc,base")
    assert settings.enabled_chains == ("solana", "ethereum", "bsc", "base")

def test_csv_environment_values(monkeypatch):
    monkeypatch.setenv("DEFAULT_MILESTONES","1.25,1.5,2,3")
    monkeypatch.setenv("ENABLED_CHAINS","solana,ethereum,bsc")
    settings=Settings(_env_file=None)
    assert settings.default_milestones==(Decimal("1.25"),Decimal("1.5"),Decimal("2"),Decimal("3"))
    assert settings.enabled_chains==("solana","ethereum","bsc")

def test_ai_disabled_without_credentials():
    from app.scanner.ai_analyzer import AIAnalyzer
    assert AIAnalyzer(Settings(_env_file=None)).client is None

@pytest.mark.asyncio
async def test_ai_failure_opens_circuit_without_raising(monkeypatch):
    from app.scanner.ai_analyzer import AIAnalyzer
    settings=Settings(_env_file=None,ai_api_key="test",ai_timeout_seconds=1)
    ai=AIAnalyzer(settings)
    async def fail(**kwargs): raise RuntimeError("provider down")
    monkeypatch.setattr(ai.client.chat.completions,"create",fail)
    assert await ai.analyze(None) is None
    assert not ai.available
