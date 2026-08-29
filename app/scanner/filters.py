from decimal import Decimal
from app.config import Settings
from app.domain import FilterResult, TokenSnapshot

class FilterEngine:
    def __init__(self, settings: Settings): self.settings=settings
    def evaluate(self, s: TokenSnapshot) -> FilterResult:
        checks=[("liquidity",s.liquidity,lambda v:v>=self.settings.min_liquidity_usd,"Minimum liquidity not met"),("volume_24h",s.volume_24h,lambda v:v>=self.settings.min_volume_24h_usd,"Minimum 24h volume not met"),("transactions",s.transactions,lambda v:v>=self.settings.min_txns_24h,"Minimum transactions not met")]
        reasons=[]; missing=[]; present=0; passed=True
        for name,value,predicate,reason in checks:
            if value is None: missing.append(name); continue
            present+=1
            if not predicate(value): passed=False; reasons.append(reason)
        if s.top_holder_percentage is not None and s.top_holder_percentage>self.settings.max_top_holder_percent: passed=False; reasons.append("Top-holder concentration too high")
        quality=Decimal(present)/Decimal(len(checks))
        if quality<self.settings.min_data_quality: passed=False; reasons.append("Insufficient data quality")
        return FilterResult(passed=passed,reasons=reasons,missing=missing,data_quality=quality)
