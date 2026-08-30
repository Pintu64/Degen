from app.config import Settings
from app.domain import CandidateAnalysis, RiskLevel, RiskVerdict
from app.scanner.degen import DegenRanker, degen_tier

class AlertEngine:
    def __init__(self, settings: Settings, ranker: DegenRanker | None = None):
        self.settings = settings
        self.ranker = ranker or DegenRanker(settings)

    def should_alert(self, a: CandidateAnalysis) -> tuple[bool, str]:
        if a.data_conflict:
            return False, "DATA CONFLICT"
        if a.snapshot.price is None or a.snapshot.price <= 0:
            return False, "INVALID PRICE"
        if a.risk.level == RiskLevel.HIGH:
            return False, "HIGH RISK"
        if not self.ranker.prefilter_ok(a):
            rating = self.ranker.rate(a)
            return False, (rating.rejections[0] if rating.rejections else "PREFILTER")
        if a.deep_risk is None or a.deep_risk.verdict == RiskVerdict.UNSCANNED:
            return False, "RISK UNSCANNED"
        if not self.ranker.may_call(a):
            if a.deep_risk.verdict == RiskVerdict.FAIL:
                return False, a.deep_risk.critical[0] if a.deep_risk.critical else "RISK FAIL"
            return False, "SCORE BELOW CALL THRESHOLD"
        return True, "QUALIFIED"

    def level(self, score: int) -> str:
        return degen_tier(score)
