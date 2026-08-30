from __future__ import annotations

from decimal import Decimal
from html import escape

from app.domain import CandidateAnalysis, Chain, TokenSnapshot

EXPLORERS = {
    Chain.SOLANA: "https://solscan.io/token/{address}",
    Chain.ETHEREUM: "https://etherscan.io/token/{address}",
    Chain.BSC: "https://bscscan.com/token/{address}",
}


def money(v: Decimal | None) -> str:
    if v is None or not v.is_finite():
        return "Data unavailable"
    precision = 18 if abs(v) < 1 else 8
    rendered = f"{v:,.{precision}f}".rstrip("0").rstrip(".")
    return f"${rendered or '0'}"


def compact(v: Decimal | None) -> str:
    if v is None or not v.is_finite():
        return "Data unavailable"
    for n, s in ((Decimal("1000000000"), "B"), (Decimal("1000000"), "M"), (Decimal("1000"), "K")):
        if abs(v) >= n:
            return f"${v / n:.2f}{s}"
    return money(v)


def pct(value: Decimal | None) -> str:
    return "Data unavailable" if value is None or not value.is_finite() else f"{value}%"


def bar(score: int, width: int = 10) -> str:
    filled = max(0, min(width, round(score / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def explorer_url(chain: Chain, address: str) -> str:
    return EXPLORERS[chain].format(address=address)


def chart_url_for(snapshot: TokenSnapshot | None, chain: str | None = None, pair_address: str | None = None) -> str | None:
    if snapshot and snapshot.chart_url:
        return str(snapshot.chart_url)
    if snapshot and snapshot.pair_address:
        return f"https://dexscreener.com/{snapshot.chain.value}/{snapshot.pair_address}"
    if chain and pair_address:
        return f"https://dexscreener.com/{chain}/{pair_address}"
    return None


def _change(value: Decimal | None) -> str:
    return pct(value)


def alert_text(a: CandidateAnalysis, call_id: int) -> str:
    s = a.snapshot
    positives = "\n".join(f"+ {escape(x)}" for x in a.score.positive_signals) or "Data unavailable"
    negatives = "\n".join(f"- {escape(x)}" for x in a.score.negative_signals) or "None identified from supplied data"
    ai_summary = (a.ai_summary[:1200] + "...") if a.ai_summary and len(a.ai_summary) > 1200 else a.ai_summary
    ai = f"\n\n<b>AI analysis</b>\n{escape(ai_summary)}" if ai_summary else ""
    symbol = escape(s.symbol or "UNKNOWN")
    return (
        f"<b>MARKET ALERT</b>\n\n"
        f"<b>${symbol}</b> | {s.chain.value.upper()}\n"
        f"Call #{call_id}\n"
        f"{bar(a.score.score)} <b>{a.score.score}/100</b>\n\n"
        f"Price: {money(s.price)}\n"
        f"Market Cap: {compact(s.market_cap)}\n"
        f"Liquidity: {compact(s.liquidity)}\n"
        f"Volume 1H / 6H / 24H: {compact(s.volume_1h)} / {compact(s.volume_6h)} / {compact(s.volume_24h)}\n"
        f"Change 1H / 6H / 24H: {_change(s.price_change_1h)} / {_change(s.price_change_6h)} / {_change(s.price_change_24h)}\n"
        f"Buys / Sells: {s.buys if s.buys is not None else 'Data unavailable'} / {s.sells if s.sells is not None else 'Data unavailable'}\n\n"
        f"Score: <b>{a.score.score}/100</b> ({a.score.confidence} confidence)\n"
        f"Risk: <b>{escape(a.risk.level.value)}</b>\n\n"
        f"<b>Positive signals</b>\n{positives}\n\n"
        f"<b>Risks / negatives</b>\n{negatives}{ai}\n\n"
        f"Contract: <code>{escape(s.contract_address)}</code>\n"
        f"Reference price permanently recorded: {money(s.price)}\n"
        f"Tracking started.\n\n"
        f"Research and paper-tracking alert. Crypto assets are highly volatile; this alert does not guarantee future performance."
    )


def start_text() -> str:
    return (
        "<b>Private Degen Scanner</b>\n\n"
        "Owner-only paper tracker for Solana, Ethereum, and BNB Chain.\n"
        "It records alerts, reference prices, milestones, ATH, and losing calls. No wallet keys required.\n\n"
        "<b>Commands</b>\n"
        "/scan — live candidates\n"
        "/scan sol | eth | bsc — one chain\n"
        "/status — worker health\n"
        "/active — open calls\n"
        "/history — recent calls\n"
        "/stats — paper performance\n"
        "/call ID — call card\n"
        "/close ID — stop tracking\n"
        "/settings — thresholds\n\n"
        "Paste a contract or DexScreener URL to look it up. Use Track on a result to start paper tracking."
    )


def status_text(scanner: str, tracker: str, telegram: str, db: str, redis_status: str, active: int, chains: tuple[str, ...]) -> str:
    def mark(value: str) -> str:
        return "online" if value == "ONLINE" else "offline"

    chain_lines = "\n".join(
        f"{name.title()}: {'enabled' if name in chains else 'disabled'}"
        for name in ("solana", "ethereum", "bsc")
    )
    return (
        "<b>System status</b>\n\n"
        f"Scanner: {mark(scanner)}\n"
        f"Tracker: {mark(tracker)}\n"
        f"Telegram queue: {mark(telegram)}\n"
        f"Database: {mark(db)}\n"
        f"Redis: {mark(redis_status)}\n"
        f"Active calls: {active}\n\n"
        f"{chain_lines}"
    )


def active_text(calls) -> str:
    if not calls:
        return "<b>Active tracking</b>\n\nNo active calls. Run /scan and tap Track on a candidate."
    lines = ["<b>Active tracking</b>\n"]
    for call in calls[:20]:
        symbol = escape(call.token.symbol or "UNKNOWN")
        chain = call.token.chain.upper()
        lines.append(
            f"#{call.id} <b>${symbol}</b> [{chain}]  {call.current_multiple:.2f}X  "
            f"ATH {call.highest_multiple:.2f}X"
        )
    return "\n".join(lines)


def history_text(calls) -> str:
    if not calls:
        return "<b>Call history</b>\n\nNo calls recorded yet."
    lines = ["<b>Call history</b>\n"]
    for call in calls[:20]:
        symbol = escape(call.token.symbol or "UNKNOWN")
        lines.append(
            f"#{call.id} <b>${symbol}</b>  {escape(call.status)}  "
            f"{call.current_multiple:.2f}X  ATH {call.highest_multiple:.2f}X"
        )
    return "\n".join(lines)


def stats_text(stats: dict) -> str:
    marks = "\n".join(f"{escape(str(k))}X reached: {v}" for k, v in stats["milestones"].items()) or "No milestones hit yet."
    return (
        "<b>Paper performance</b>\n\n"
        f"Total calls: {stats['total']}\n"
        f"Active: {stats['active']}\n"
        f"Closed: {stats['closed']}\n"
        f"Average ATH: {stats['average_ath']:.2f}X\n"
        f"Median ATH: {stats['median_ath']:.2f}X\n"
        f"Maximum ATH: {stats['maximum_ath']:.2f}X\n"
        f"Below 1X: {stats['below_1x']}\n"
        f"At or above 1X: {stats['above_1x']}\n\n"
        f"{marks}"
    )


def settings_text(settings) -> str:
    chains = ", ".join(settings.enabled_chains)
    milestones = ", ".join(str(item) for item in settings.default_milestones)
    return (
        "<b>Settings</b>\n\n"
        "Loaded from environment variables. Change them in <code>.env</code> or Railway, then restart.\n\n"
        f"Minimum score: {settings.min_score}\n"
        f"Minimum liquidity: {compact(settings.min_liquidity_usd)}\n"
        f"Minimum 24h volume: {compact(settings.min_volume_24h_usd)}\n"
        f"Minimum transactions: {settings.min_txns_24h}\n"
        f"Scan interval: {settings.scan_interval_seconds}s\n"
        f"Tracking interval: {settings.tracking_interval_seconds}s\n"
        f"Chains: {escape(chains)}\n"
        f"Milestones: {escape(milestones)}\n"
        f"AI: {'on' if settings.ai_enabled and settings.ai_api_key else 'off'}"
    )


def scan_list_text(candidates: list[CandidateAnalysis], label: str) -> str:
    if not candidates:
        return (
            f"<b>Scan · {escape(label)}</b>\n\n"
            "No live candidates from DexScreener right now. Try another chain or paste a contract."
        )
    lines = [f"<b>Scan · {escape(label)}</b>\n"]
    for index, analysis in enumerate(candidates[:8], 1):
        s = analysis.snapshot
        symbol = escape(s.symbol or "UNKNOWN")
        change = pct(s.price_change_1h)
        lines.append(
            f"{index}. <b>${symbol}</b> [{s.chain.value}]\n"
            f"{bar(analysis.score.score)} {analysis.score.score}/100  "
            f"{compact(s.liquidity)} liq  {change} 1h"
        )
    lines.append("\nTap a token for the full card, then Track to paper-trade it.")
    return "\n".join(lines)


def candidate_text(analysis: CandidateAnalysis) -> str:
    s = analysis.snapshot
    symbol = escape(s.symbol or "UNKNOWN")
    name = escape(s.name or "Unknown token")
    positives = "\n".join(f"+ {escape(x)}" for x in analysis.score.positive_signals) or "None from supplied data"
    negatives = "\n".join(f"- {escape(x)}" for x in analysis.score.negative_signals) or "None identified"
    reasons = "\n".join(f"- {escape(x)}" for x in analysis.filters.reasons) or "Passed configured filters"
    return (
        f"<b>${symbol}</b> · {name}\n"
        f"{s.chain.value.upper()} · {escape(s.dex or 'unknown dex')}\n"
        f"{bar(analysis.score.score)} <b>{analysis.score.score}/100</b> ({analysis.score.confidence})\n"
        f"Risk: <b>{escape(analysis.risk.level.value)}</b>\n\n"
        f"Price: {money(s.price)}\n"
        f"Market cap: {compact(s.market_cap)}\n"
        f"Liquidity: {compact(s.liquidity)}\n"
        f"Volume 1H / 6H / 24H: {compact(s.volume_1h)} / {compact(s.volume_6h)} / {compact(s.volume_24h)}\n"
        f"Change 1H / 6H / 24H: {_change(s.price_change_1h)} / {_change(s.price_change_6h)} / {_change(s.price_change_24h)}\n"
        f"Buys / Sells: {s.buys if s.buys is not None else 'n/a'} / {s.sells if s.sells is not None else 'n/a'}\n\n"
        f"<b>Signals</b>\n{positives}\n\n"
        f"<b>Negatives</b>\n{negatives}\n\n"
        f"<b>Filters</b>\n{reasons}\n\n"
        f"Contract: <code>{escape(s.contract_address)}</code>"
    )


def call_text(call) -> str:
    symbol = escape(call.token.symbol or "UNKNOWN")
    marks = []
    for milestone in sorted(call.milestones, key=lambda item: item.target_multiple):
        flag = "HIT" if milestone.status == "HIT" else "open"
        marks.append(f"[{flag}] {milestone.target_multiple}X")
    milestone_block = "\n".join(marks) or "No milestones"
    return (
        f"<b>Call #{call.id}</b> · {escape(call.status)}\n\n"
        f"<b>${symbol}</b> | {call.token.chain.upper()}\n"
        f"Reference: {money(call.reference_price)}\n"
        f"Current: {money(call.current_price)}\n"
        f"Multiple: <b>{call.current_multiple:.2f}X</b>\n"
        f"Observed ATH: {call.highest_multiple:.2f}X\n\n"
        f"<b>Milestones</b>\n{milestone_block}\n\n"
        f"Contract: <code>{escape(call.token.contract_address)}</code>"
    )


def milestone_text(call, milestone, multiple: Decimal, extra: str = "") -> str:
    symbol = escape(call.token.symbol or "UNKNOWN")
    details = f"\n{extra.strip()}" if extra.strip() else ""
    return (
        f"<b>MILESTONE HIT</b>\n\n"
        f"<b>${symbol}</b> · {milestone.target_multiple}X\n\n"
        f"Reference: {money(call.reference_price)}\n"
        f"Hit price: {money(milestone.hit_price)}\n"
        f"Multiple: {multiple:.2f}X{details}\n\n"
        f"Price reached {milestone.target_multiple}X relative to the recorded reference price."
    )


def recovery_alert_text(call) -> str:
    symbol = escape(call.token.symbol or "UNKNOWN")
    return (
        f"<b>MARKET ALERT</b>\n\n"
        f"<b>${symbol}</b> | {call.token.chain.upper()}\n"
        f"Call #{call.id}\n\n"
        f"Reference price: {money(call.reference_price)}\n"
        f"Initial score: {call.initial_score}/100\n"
        f"Risk: {escape(call.initial_risk)}\n\n"
        f"Tracking is active. Research and paper-tracking alert; this does not guarantee future performance."
    )


def call_usage() -> str:
    return "Usage: /call ID\nExample: /call 12"


def close_usage() -> str:
    return "Usage: /close ID\nExample: /close 12"
