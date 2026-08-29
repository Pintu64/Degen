from app.domain import RiskAssessment, RiskLevel, TokenSnapshot

class RiskAnalyzer:
    def assess(self,s:TokenSnapshot)->RiskAssessment:
        risks=[]; positive=[]; missing=[]
        if s.liquidity is None: missing.append("liquidity")
        if s.top_holder_percentage is None: missing.append("holder concentration")
        if s.chain.value=="solana":
            if s.mint_authority is None: missing.append("mint authority")
            elif s.mint_authority: risks.append("Mint authority enabled")
            if s.freeze_authority is None: missing.append("freeze authority")
            elif s.freeze_authority: risks.append("Freeze authority enabled")
        else:
            if s.contract_verified is None: missing.append("contract verification")
            elif not s.contract_verified: risks.append("Contract not verified")
            if s.buy_tax is None or s.sell_tax is None: missing.append("tax data")
        risks.extend(s.suspicious_flags)
        level=RiskLevel.HIGH if len(risks)>=2 else RiskLevel.MEDIUM if risks else RiskLevel.UNKNOWN if missing else RiskLevel.LOWER
        if s.liquidity is not None: positive.append("Liquidity reported by provider")
        return RiskAssessment(level=level,positive_signals=positive,risk_signals=risks,missing_information=missing)
