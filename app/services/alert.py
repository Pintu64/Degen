from app.config import Settings
from app.domain import CandidateAnalysis, RiskLevel

class AlertEngine:
    def __init__(self,settings:Settings): self.settings=settings
    def should_alert(self,a:CandidateAnalysis)->tuple[bool,str]:
        if a.data_conflict:return False,"DATA CONFLICT"
        if not a.filters.passed:return False,"FILTERED"
        if a.risk.level==RiskLevel.HIGH:return False,"HIGH RISK"
        if a.score.score<self.settings.min_score:return False,"SCORE BELOW MINIMUM"
        if a.snapshot.price is None or a.snapshot.price<=0:return False,"INVALID PRICE"
        return True,"QUALIFIED"
    def level(self,score:int)->str:
        if score>=self.settings.extreme_score:return "EXTREME"
        if score>=self.settings.strong_score:return "STRONG"
        if score>=self.settings.interesting_score:return "INTERESTING"
        return "WATCH"
