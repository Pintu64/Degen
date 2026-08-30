from decimal import Decimal
from tests.test_analysis import snapshot
from app.bot.formatting import alert_text, clip_html, checking_text
from app.config import Settings
from app.domain import CandidateAnalysis
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine

def test_zero_change_is_not_reported_as_unavailable():
    s=snapshot(price_change_1h=Decimal("0")); risk=RiskAnalyzer().assess(s)
    analysis=CandidateAnalysis(snapshot=s,filters=FilterEngine(Settings()).evaluate(s),risk=risk,score=ScoringEngine(Settings()).score(s,risk))
    text = alert_text(analysis, 1)
    assert "5m" in text
    assert "1h" in text
    assert "0%" in text
    assert "DEGEN CALL" in text


def test_clip_html_stays_under_telegram_limit():
    text = clip_html("line\n" * 3000)
    assert len(text) <= 4096
    assert clip_html("short") == "short"


def test_checking_text_mentions_the_scan():
    text = checking_text()
    assert "honeypot" in text.lower()
