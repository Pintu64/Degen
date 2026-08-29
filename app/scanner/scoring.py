from decimal import Decimal
from app.config import Settings
from app.domain import RiskAssessment, RiskLevel, ScoreResult, TokenSnapshot

class ScoringEngine:
    def __init__(self,settings:Settings): self.settings=settings
    def score(self,s:TokenSnapshot,risk:RiskAssessment)->ScoreResult:
        points=0; pos=[]; neg=[]
        metrics=[(s.liquidity is not None and s.liquidity>=self.settings.min_liquidity_usd,20,"Meaningful liquidity"),(s.volume_24h is not None and s.volume_24h>=self.settings.min_volume_24h_usd,15,"Strong reported volume"),(s.price_change_1h is not None and s.price_change_1h>0,15,"Positive short-term momentum"),(s.price_change_6h is not None and s.price_change_6h>0,15,"Positive medium-term momentum"),(s.transactions is not None and s.transactions>=self.settings.min_txns_24h,15,"Active transactions"),(s.buys is not None and s.sells is not None and s.buys>=s.sells,10,"Buy activity at or above sells"),(s.top_holder_percentage is not None and s.top_holder_percentage<self.settings.max_top_holder_percent,10,"Holder distribution within range")]
        known=sum(1 for values in [(s.liquidity,),(s.volume_24h,),(s.price_change_1h,),(s.price_change_6h,),(s.transactions,),(s.buys,s.sells),(s.top_holder_percentage,)] if all(v is not None for v in values))
        for condition,weight,label in metrics:
            if condition: points+=weight; pos.append(label)
        if risk.level==RiskLevel.HIGH: points-=20
        elif risk.level==RiskLevel.UNKNOWN: points-=5; neg.append("Critical risk data unavailable")
        neg.extend(risk.risk_signals); coverage=Decimal(known)/Decimal(len(metrics)); confidence="High" if coverage>=Decimal("0.85") else "Medium" if coverage>=Decimal("0.55") else "Low"
        return ScoreResult(score=max(0,min(100,points)),confidence=confidence,positive_signals=pos,negative_signals=list(dict.fromkeys(neg)),coverage=coverage)
