from app.config import Settings
from app.domain import CandidateAnalysis, TokenSnapshot
from app.scanner.degen import DegenRanker
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine

class AnalysisService:
    def __init__(self, filters: FilterEngine, risk: RiskAnalyzer, scoring: ScoringEngine, degen: DegenRanker | None = None, settings: Settings | None = None):
        self.filters = filters
        self.risk = risk
        self.scoring = scoring
        self.degen = degen or DegenRanker(settings or Settings(_env_file=None))

    def analyze(self, s: TokenSnapshot) -> CandidateAnalysis:
        filters = self.filters.evaluate(s)
        risk = self.risk.assess(s)
        score = self.scoring.score(s, risk)
        return self.degen.apply(CandidateAnalysis(snapshot=s, filters=filters, risk=risk, score=score))

    def select_best(self, candidates: list[CandidateAnalysis], limit: int | None = None) -> list[CandidateAnalysis]:
        return self.degen.select_best(candidates, limit)
