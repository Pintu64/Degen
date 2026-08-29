from decimal import Decimal
from tests.test_analysis import snapshot
from app.bot.formatting import alert_text
from app.config import Settings
from app.domain import CandidateAnalysis
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine

def test_zero_change_is_not_reported_as_unavailable():
    s=snapshot(price_change_1h=Decimal("0")); risk=RiskAnalyzer().assess(s)
    analysis=CandidateAnalysis(snapshot=s,filters=FilterEngine(Settings()).evaluate(s),risk=risk,score=ScoringEngine(Settings()).score(s,risk))
    assert "Change 1H / 6H / 24H: 0%" in alert_text(analysis,1)
