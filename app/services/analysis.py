from app.domain import CandidateAnalysis, TokenSnapshot
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine

class AnalysisService:
    def __init__(self,filters:FilterEngine,risk:RiskAnalyzer,scoring:ScoringEngine): self.filters=filters; self.risk=risk; self.scoring=scoring
    def analyze(self,s:TokenSnapshot)->CandidateAnalysis:
        f=self.filters.evaluate(s); r=self.risk.assess(s); score=self.scoring.score(s,r); return CandidateAnalysis(snapshot=s,filters=f,risk=r,score=score)
