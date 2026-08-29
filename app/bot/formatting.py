from decimal import Decimal
from html import escape
from app.domain import CandidateAnalysis

def money(v:Decimal|None)->str: return "Data unavailable" if v is None else f"${v:,.8f}".rstrip("0").rstrip(".")
def compact(v:Decimal|None)->str:
    if v is None:return "Data unavailable"
    for n,s in ((Decimal("1000000000"),"B"),(Decimal("1000000"),"M"),(Decimal("1000"),"K")):
        if abs(v)>=n:return f"${v/n:.2f}{s}"
    return money(v)
def alert_text(a:CandidateAnalysis,call_id:int)->str:
    s=a.snapshot; positives="\n".join(f"+ {escape(x)}" for x in a.score.positive_signals) or "Data unavailable"; negatives="\n".join(f"- {escape(x)}" for x in a.score.negative_signals) or "None identified from supplied data"
    change=lambda value: "Data unavailable" if value is None else f"{value}%"
    ai_summary=(a.ai_summary[:1200]+"...") if a.ai_summary and len(a.ai_summary)>1200 else a.ai_summary
    ai=f"\n\n<b>AI analysis</b>\n{escape(ai_summary)}" if ai_summary else ""
    return f"<b>MARKET ALERT</b>\n\n<b>${escape(s.symbol or 'UNKNOWN')}</b> | {s.chain.value.upper()}\nCall #{call_id}\n\nPrice: {money(s.price)}\nMarket Cap: {compact(s.market_cap)}\nLiquidity: {compact(s.liquidity)}\nVolume 1H / 6H / 24H: {compact(s.volume_1h)} / {compact(s.volume_6h)} / {compact(s.volume_24h)}\nChange 1H / 6H / 24H: {change(s.price_change_1h)} / {change(s.price_change_6h)} / {change(s.price_change_24h)}\nBuys / Sells: {s.buys if s.buys is not None else 'Data unavailable'} / {s.sells if s.sells is not None else 'Data unavailable'}\n\nScore: <b>{a.score.score}/100</b> ({a.score.confidence} confidence)\nRisk: <b>{a.risk.level.value}</b>\n\n<b>Positive signals</b>\n{positives}\n\n<b>Risks / negatives</b>\n{negatives}{ai}\n\nContract: <code>{escape(s.contract_address)}</code>\nReference price permanently recorded: {money(s.price)}\nTracking started.\n\nResearch and paper-tracking alert. Crypto assets are highly volatile; this alert does not guarantee future performance."
