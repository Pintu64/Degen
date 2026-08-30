from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape

from app.bot.charts import momentum_points, pressure_bar, sparkline
from app.domain import CandidateAnalysis, Chain, CoinScan, DeepRiskReport, RiskVerdict, TokenSnapshot

EXPLORERS = {
    Chain.SOLANA: "https://solscan.io/token/{address}",
    Chain.ETHEREUM: "https://etherscan.io/token/{address}",
    Chain.BSC: "https://bscscan.com/token/{address}",
    Chain.BASE: "https://basescan.org/token/{address}",
}

CHAIN_BADGE = {
    "solana": "🟣 SOL",
    "ethereum": "💠 ETH",
    "bsc": "🟡 BNB",
    "base": "🔵 BASE",
}

RISK_EMOJI = {
    "LOWER RISK": "🟢",
    "MEDIUM RISK": "🟡",
    "HIGH RISK": "🔴",
    "UNKNOWN": "⚪",
}

ALERT_FLAIR = {
    "S+": "🚀💎  DEGEN CALL  ·  S+",
    "A": "🔥  DEGEN CALL  ·  A",
    "B": "⚡  DEGEN CALL  ·  B",
    "F": "👀  WATCH  ·  F — not an official call",
    "WATCH": "👀  WATCHLIST DEGEN",
    "INTERESTING": "⚡  INTERESTING DEGEN",
    "STRONG": "🔥  STRONG DEGEN CALL",
    "EXTREME": "🚀💎  EXTREME DEGEN CALL",
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


def signed_pct(value: Decimal | None) -> str:
    if value is None or not value.is_finite():
        return "Data unavailable"
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value}%"


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
    return signed_pct(value)


def _chain_badge(chain: Chain | str | None) -> str:
    if chain is None or chain == "":
        return "🌐"
    key = chain.value if isinstance(chain, Chain) else str(chain).lower()
    return CHAIN_BADGE.get(key, escape(str(chain).upper()))


def _score_emoji(score: int) -> str:
    if score >= 90:
        return "🚀"
    if score >= 80:
        return "🔥"
    if score >= 70:
        return "⚡"
    if score >= 60:
        return "👀"
    return "🧊"


def _risk_badge(level: str) -> str:
    return f"{RISK_EMOJI.get(level, '⚪')} {escape(level)}"


def _panel(content: str, *, expandable: bool = False) -> str:
    open_tag = "blockquote expandable" if expandable else "blockquote"
    return f"<{open_tag}>{content}</blockquote>"


def glass_card(title: str, body: str, *, kicker: str = "frosted · owner desk", expandable: bool = False) -> str:
    header = f"<b>{title}</b>\n<i>✦  {escape(kicker)}</i>"
    return f"{header}\n\n{_panel(body, expandable=expandable)}"


def clip_html(text: str, limit: int = 4096) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 8]
    newline = cut.rfind("\n")
    if newline > limit // 2:
        cut = cut[:newline]
    return cut + "\n…"


def _metrics(*rows: tuple[str, str]) -> str:
    return "\n".join(f"{label}  <b>{value}</b>" for label, value in rows)


def _pair(left, right, missing: str = "Data unavailable") -> str:
    return f"{left if left is not None else missing} / {right if right is not None else missing}"


def elapsed_text(elapsed: timedelta) -> str:
    seconds = max(0, int(elapsed.total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def age_text(seconds: int | None) -> str:
    if seconds is None:
        return "Data unavailable"
    return elapsed_text(timedelta(seconds=max(0, seconds)))


def _chart_block(snapshot: TokenSnapshot) -> str:
    points = momentum_points(snapshot)
    tape = sparkline(points)
    pressure = pressure_bar(snapshot.buys, snapshot.sells)
    return (
        f"📈 <b>Mini chart</b>  <code>{tape}</code>\n"
        f"5m {_change(snapshot.price_change_m5)}  ·  1h {_change(snapshot.price_change_1h)}  ·  "
        f"6h {_change(snapshot.price_change_6h)}  ·  24h {_change(snapshot.price_change_24h)}\n"
        f"⚔ Buy/Sell  {pressure}"
    )


def deep_risk_block(report: DeepRiskReport | None) -> str:
    if report is None:
        return "🛡 <b>RISK</b>  ⚪ UNSCANNED — illegal to official-call"
    labels = {
        RiskVerdict.PASS: "✅ PASS",
        RiskVerdict.PASS_WITH_WARN: "⚠️ PASS WITH WARN",
        RiskVerdict.FAIL: "🛑 FAIL — do not call",
        RiskVerdict.UNSCANNED: "⚪ UNSCANNED",
    }
    lines = [f"🛡 <b>RISK</b>  {labels.get(report.verdict, report.verdict.value)}"]
    for item in report.critical[:4]:
        lines.append(f"🛑 {escape(item)}")
    for item in report.warnings[:3]:
        lines.append(f"⚠️ {escape(item)}")
    for check in report.checks:
        if check.result == "PASS" and check.name in {"honeypot", "mint", "freeze", "holders", "lp", "tax"}:
            lines.append(f"• {escape(check.name)}: {escape(check.evidence)}")
    return "\n".join(lines[:12])


def coin_scan_block(scan: CoinScan | None, snapshot: TokenSnapshot | None = None) -> str:
    if scan is None and snapshot is not None:
        scan = CoinScan(
            mint_authority=snapshot.mint_authority,
            freeze_authority=snapshot.freeze_authority,
            ownership_renounced=snapshot.ownership_renounced,
            buy_tax=snapshot.buy_tax,
            sell_tax=snapshot.sell_tax,
            holders=snapshot.holders,
            top10_percent=snapshot.top_holder_percentage,
            verified=snapshot.contract_verified,
            flags=list(snapshot.suspicious_flags or []),
            source="snapshot",
        )
        from app.scanner.security import finalize
        scan = finalize(scan)
    if scan is None:
        return "🔬 <b>COIN SCAN</b>\n❔ Mint / holders / honeypot not available from this provider."
    holders = f"{scan.holders:,}" if scan.holders is not None else "n/a"
    top10 = f"{scan.top10_percent:.1f}%" if scan.top10_percent is not None else "n/a"
    buy = f"{scan.buy_tax:.1f}%" if scan.buy_tax is not None else "n/a"
    sell = f"{scan.sell_tax:.1f}%" if scan.sell_tax is not None else "n/a"
    lp = scan.checks.get("lp", "❔ UNKNOWN")
    if scan.lp_locked_percent is not None:
        lp = f"{lp} ({scan.lp_locked_percent:.0f}%)"
    safety = f"{scan.safety_score}/100" if scan.safety_score is not None else "n/a"
    fatal = "🛑 <b>FATAL — do not size this</b>\n" if scan.fatal else ""
    extra = ""
    if scan.flags:
        extra = "\n⚠️ " + " · ".join(escape(flag) for flag in scan.flags[:4])
    return (
        f"🔬 <b>COIN SCAN</b>  ·  safety {safety}  ·  {escape(scan.source)}\n"
        f"{fatal}"
        f"🍯 Honeypot   {scan.checks.get('honeypot', '❔')}\n"
        f"🪙 Mint       {scan.checks.get('mint', '❔')}\n"
        f"❄️ Freeze     {scan.checks.get('freeze', '❔')}\n"
        f"👤 Owner      {scan.checks.get('owner', '❔')}\n"
        f"👥 Holders    <b>{holders}</b>   top10 <b>{top10}</b>\n"
        f"🧪 Tax        buy {buy} / sell {sell}\n"
        f"🔒 LP lock    {lp}\n"
        f"📄 Contract   {scan.checks.get('verified', '❔')}\n"
        f"🚫 Blacklist  {scan.checks.get('blacklist', '❔')}\n"
        f"🧩 Proxy      {scan.checks.get('proxy', '❔')}"
        f"{extra}"
    )


def _degen_block(analysis: CandidateAnalysis) -> str:
    reasons = "\n".join(f"✨ {escape(item)}" for item in analysis.degen_reasons[:4]) or "No extra degen tags"
    stamp = "🏆 <b>BEST DEGEN PICK</b>" if analysis.degen_score >= 80 else "🎯 Degen desk"
    late = "\n⏰ Too late for a fresh entry — already vertical." if analysis.too_late else ""
    return f"{stamp}\n🎯 Degen score  <b>{analysis.degen_score}/100</b>\n{reasons}{late}"


def _pump_percent(multiple: Decimal) -> str:
    change = (multiple - Decimal("1")) * Decimal("100")
    prefix = "+" if change >= 0 else ""
    return f"{prefix}{change:.2f}%"


def pump_status(multiple: Decimal, ath: Decimal | None = None) -> tuple[str, str]:
    change = (multiple - Decimal("1")) * Decimal("100")
    if change >= 100:
        return "🌙 MOON", "🚀"
    if change >= 20:
        return "🔥 COOKING", "🔥"
    if change >= Decimal("-15"):
        return "⚔️ CHOP", "⚔️"
    if change >= Decimal("-60"):
        return "📉 DUMPING", "📉"
    return "💀 REKT", "💀"


def mc_lp_ratio(mc: Decimal | None, liq: Decimal | None) -> str:
    if mc is None or liq is None or liq <= 0:
        return "Data unavailable"
    return f"{(mc / liq):.2f}"


def pump_after_call_block(calls, live_price: Decimal | None, history=None, live_mc: Decimal | None = None) -> str:
    if not calls:
        return (
            "❌ <b>NOT CALLED BY BOT</b>\n"
            "This contract has never been called by this desk.\n"
            "Live 5m / 1h / 6h / 24h is still on the card.\n"
            "Hit 📌 Track this CA to start watching from NOW."
        )
    call = calls[0]
    reference = call.reference_price
    current = live_price if live_price is not None and live_price > 0 else call.current_price
    multiple = (current / reference) if reference and reference > 0 and current and current > 0 else call.current_multiple
    started = call.reference_timestamp
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = elapsed_text(datetime.now(UTC) - started)
    label, emoji = pump_status(multiple)
    ath_pct = _pump_percent(call.highest_multiple)
    drawdown = ""
    if call.highest_multiple and call.highest_multiple > 0:
        dd = (Decimal("1") - (multiple / call.highest_multiple)) * Decimal("100")
        drawdown = f"\n📉 Drawdown from ATH  <b>{dd:.2f}%</b>"
    entry_mc = getattr(call, "initial_market_cap", None)
    now_mc = live_mc if live_mc is not None else None
    mc_line = ""
    if entry_mc:
        mc_line = f"\n🏦 Entry MC  {compact(entry_mc)}"
        if now_mc:
            mc_line += f"   →   Now  {compact(now_mc)}"
    tape = ""
    if history:
        multiples = [row.multiple for row in history if getattr(row, "multiple", None) is not None]
        if multiples:
            tape = f"\n📉 Tape after call  <code>{sparkline(multiples)}</code>"
    more = f"\n📚 Older calls on this contract: <b>{len(calls) - 1}</b>" if len(calls) > 1 else ""
    source = getattr(call, "source", "OFFICIAL") or "OFFICIAL"
    return (
        f"✅ <b>BOT CALLED THIS</b>  ·  {elapsed} ago\n"
        f"{emoji} Call #{call.id} · {escape(source)} · {label}\n"
        f"{_metrics(
            ('🔒 Called at', money(reference)),
            ('💵 Now', money(current)),
            ('🚀 PUMP AFTER CALL', f'{multiple:.2f}X  ({_pump_percent(multiple)})'),
            ('🏆 ATH AFTER CALL', f'{call.highest_multiple:.2f}X  ({ath_pct})'),
        )}"
        f"{mc_line}{drawdown}{tape}{more}"
    )


def alert_text(a: CandidateAnalysis, call_id: int, level: str | None = None) -> str:
    s = a.snapshot
    why_src = [item for item in (a.degen_reasons or []) if not item.startswith("Passed every")][:3]
    why = "\n".join(f"• {escape(x)}" for x in why_src) or "• Highest score that cleared pre-filter + deep risk"
    symbol = escape(s.symbol or "UNKNOWN")
    name = escape(s.name or "Unknown")
    tier = (level or "B").upper()
    verdict = a.deep_risk.verdict if a.deep_risk else RiskVerdict.UNSCANNED
    warn_prefix = "⚠️ WARN  " if verdict == RiskVerdict.PASS_WITH_WARN else ""
    title = warn_prefix + ALERT_FLAIR.get(tier, "🚨🔥  DEGEN CALL")
    fresh = "⚡ fresh call" if (s.pair_age_seconds or 0) < 600 else f"⏱ Age {age_text(s.pair_age_seconds)}"
    holders = f"{a.coin_scan.holders:,}" if a.coin_scan and a.coin_scan.holders is not None else "n/a"
    top10 = f"{a.coin_scan.top10_percent:.0f}%" if a.coin_scan and a.coin_scan.top10_percent is not None else "n/a"
    body = (
        f"{_chain_badge(s.chain)}  ·  {escape((s.dex or 'dex').title())}\n"
        f"⚡ TIER <b>{escape(tier)}</b>    SCORE <b>{a.degen_score}/100</b>    🛡 {escape(verdict.value)}\n\n"
        f"🪙 <b>${symbol}</b>  —  {name}\n"
        f"<code>{escape(s.contract_address)}</code>\n\n"
        f"{_metrics(
            ('🏦 MC', compact(s.market_cap)),
            ('💧 LP', compact(s.liquidity)),
            ('📐 MC/LP', mc_lp_ratio(s.market_cap, s.liquidity)),
            ('📊 Vol', compact(s.volume_24h)),
            ('📈 5m / 1h', f'{_change(s.price_change_m5)}   {_change(s.price_change_1h)}'),
            ('🔄 Buys / Sells 5m', _pair(s.buys_m5 or s.buys, s.sells_m5 or s.sells)),
            ('👥 Holders / top10', f'{holders}   /   {top10}'),
        )}\n"
        f"{fresh}    Called at {compact(s.market_cap)} MC\n\n"
        f"{_chart_block(s)}\n\n"
        f"{deep_risk_block(a.deep_risk)}\n\n"
        f"{coin_scan_block(a.coin_scan, s)}\n\n"
        f"<b>WHY THIS ONE</b>\n{why}\n\n"
        f"📌 Official paper call #{call_id}\n"
        f"⚠️ NFA · DYOR · can go to zero · size small"
    )
    return glass_card(title, body, kicker="accuracy over volume · paper only", expandable=True)


def start_text() -> str:
    body = (
        "💎 Owner-only degen desk for Solana, Ethereum, BNB, and Base.\n"
        "It does not spam every coin — only the best degen setups survive the ranker.\n"
        "No wallet keys. Ever.\n\n"
        "🔬 <b>Default check</b> — mint · freeze · holders · honeypot · tax · LP\n"
        "🎯 <b>Best degen</b> — one official call, never a dump of 10 coins\n"
        "🔎 <b>Scan</b> — Sol / Base / ETH / BNB, still ranked not spammed\n"
        "📥 <b>/ca</b> or <b>🔬 Check</b> — paste CA (links parsed, card stays here)\n"
        "📌 <b>/track</b> · <b>/mytracks</b> — personal watch from NOW\n"
        "🌐 <b>/chains</b> — toggle Sol / Base / ETH / BNB\n"
        "📊 <b>/stats</b> — win-rate +50% / 2X / 5X\n\n"
        "If this desk already called a CA, you get PUMP AFTER CALL + status\n"
        "🌙 MOON · 🔥 COOKING · ⚔️ CHOP · 📉 DUMPING · 💀 REKT\n"
        "If it never called it: ❌ NOT CALLED BY BOT — still live tape + chart."
    )
    return glass_card("💎🚀  Private Degen Scanner", body, kicker="elite picks · frosted glass")


def scan_menu_text() -> str:
    body = (
        "This desk will not dump a bag of random coins.\n"
        "Each sweep keeps only the best degen setups.\n\n"
        "🟣 Solana · 💠 Ethereum · 🟡 BNB · 🔵 Base\n"
        "🎯 Or smash Best Degen for a single elite pick.\n\n"
        "Tap a card → full check + tape → 📌 Track."
    )
    return glass_card("🔎🎯  Degen scan desk", body, kicker="quality over quantity")


def status_text(scanner: str, tracker: str, telegram: str, db: str, redis_status: str, active: int, chains: tuple[str, ...]) -> str:
    def mark(value: str) -> str:
        return "🟢 online" if value == "ONLINE" else "🔴 offline"

    chain_lines = "\n".join(
        f"{_chain_badge(name)}  {'🟢 enabled' if name in chains else '⚪️ disabled'}"
        for name in ("solana", "ethereum", "bsc", "base")
    )
    body = (
        f"{_metrics(
            ('🛰 Scanner', mark(scanner)),
            ('📡 Tracker', mark(tracker)),
            ('✉️ Telegram queue', mark(telegram)),
            ('🗄️ Database', mark(db)),
            ('⚡ Redis', mark(redis_status)),
            ('📌 Active calls', str(active)),
        )}\n\n"
        f"{chain_lines}"
    )
    return glass_card("📡  System status", body, kicker="live heartbeats")


def active_text(calls) -> str:
    if not calls:
        return glass_card(
            "📌  Active tracking",
            "No active calls yet.\nOpen 🎯 Best degen and tap 📌 Track on the elite card.",
            kicker="empty glass",
        )
    lines = []
    for call in calls[:20]:
        symbol = escape(call.token.symbol or "UNKNOWN")
        trend = "🚀" if call.current_multiple >= 1 else "🧊"
        pump = _pump_percent(call.current_multiple)
        lines.append(
            f"{trend} #{call.id} <b>${symbol}</b> · {_chain_badge(call.token.chain)}\n"
            f"    {call.current_multiple:.2f}X  ({pump})   ·   ATH {call.highest_multiple:.2f}X"
        )
    return glass_card("📌🚀  Active tracking", "\n\n".join(lines), kicker=f"{len(calls)} live paper call(s)", expandable=len(calls) > 6)


def history_text(calls) -> str:
    if not calls:
        return glass_card("📚  Call history", "No calls recorded yet.", kicker="empty glass")
    lines = []
    for call in calls[:20]:
        symbol = escape(call.token.symbol or "UNKNOWN")
        flag = "🟢" if call.status == "ACTIVE" else "⚪️"
        trend = "🚀" if call.current_multiple >= 1 else "🧊"
        lines.append(
            f"{flag}{trend} #{call.id} <b>${symbol}</b>  {escape(call.status)}\n"
            f"    {call.current_multiple:.2f}X   ·   ATH {call.highest_multiple:.2f}X  ({_pump_percent(call.highest_multiple)})"
        )
    return glass_card("📚  Call history", "\n\n".join(lines), kicker="recent paper tape", expandable=len(calls) > 6)


def stats_text(stats: dict) -> str:
    marks = "\n".join(f"🎯 {escape(str(k))}X  ·  {v}" for k, v in stats["milestones"].items()) or "No milestones hit yet."
    avg = f"{stats['average_ath']:.2f}X"
    median = f"{stats['median_ath']:.2f}X"
    maximum = f"{stats['maximum_ath']:.2f}X"
    body = (
        f"{_metrics(
            ('📁 Total calls', str(stats['total'])),
            ('📌 Active', str(stats['active'])),
            ('⚪️ Closed', str(stats['closed'])),
            ('📈 Average ATH', avg),
            ('📊 Median ATH', median),
            ('🚀 Maximum ATH', maximum),
            ('🧊 Below 1X', str(stats['below_1x'])),
            ('🚀 At or above 1X', str(stats['above_1x'])),
            ('🎯 Hit +50%', f"{stats.get('hit_50', 0)}  ({stats.get('hit_50_pct', '0')}%)"),
            ('🔥 Hit 2X', f"{stats.get('hit_2x', 0)}  ({stats.get('hit_2x_pct', '0')}%)"),
            ('🌙 Hit 5X', f"{stats.get('hit_5x', 0)}  ({stats.get('hit_5x_pct', '0')}%)"),
        )}\n\n"
        f"{marks}"
    )
    return glass_card("📊  Paper performance", body, kicker="honest tape")


def settings_text(settings) -> str:
    chains = ", ".join(settings.enabled_chains)
    milestones = ", ".join(str(item) for item in settings.default_milestones)
    ai = "🟢 on" if settings.ai_enabled and settings.ai_api_key else "⚪️ off"
    body = (
        "Loaded from environment variables. Change them in <code>.env</code> or Railway, then restart.\n\n"
        f"{_metrics(
            ('🎯 Minimum score', str(settings.min_score)),
            ('🏆 Max degen picks', str(settings.max_degen_picks)),
            ('🚨 Alerts per cycle', str(settings.max_degen_alerts_per_cycle)),
            ('💧 Minimum liquidity', compact(settings.min_liquidity_usd)),
            ('📊 Minimum 24h volume', compact(settings.min_volume_24h_usd)),
            ('🔄 Minimum transactions', str(settings.min_txns_24h)),
            ('⏱ Scan interval', f'{settings.scan_interval_seconds}s'),
            ('📡 Tracking interval', f'{settings.tracking_interval_seconds}s'),
            ('🌐 Chains', escape(chains)),
            ('🎯 Milestones', escape(milestones)),
            ('🧠 AI', ai),
        )}"
    )
    return glass_card("⚙️  Settings", body, kicker="read-only glass")


def _check_badges(analysis: CandidateAnalysis) -> str:
    scan = analysis.coin_scan
    if scan is None:
        return "🔬 default check queued"
    honey = "🍯 CLEAN" if scan.honeypot is False else ("🍯 POT" if scan.honeypot else "🍯 ?")
    mint = "🪙 REVOKED" if scan.mint_authority is False else ("🪙 MINT OPEN" if scan.mint_authority else "🪙 ?")
    freeze = "❄️ REVOKED" if scan.freeze_authority is False else ("❄️ FREEZE OPEN" if scan.freeze_authority else "❄️ ?")
    holders = f"👥 {scan.holders:,}" if scan.holders is not None else "👥 n/a"
    top = f"top10 {scan.top10_percent:.0f}%" if scan.top10_percent is not None else ""
    fatal = " 🛑 FATAL" if scan.fatal else ""
    return f"{honey} · {mint} · {freeze} · {holders} {top}{fatal}".strip()


def scan_list_text(candidates: list[CandidateAnalysis], label: str) -> str:
    if not candidates:
        return glass_card(
            f"🔎  Best degen · {escape(label)}",
            "No tradeable pair cleared the desk this sweep.\n"
            "Official calls stay silent unless risk PASS + score ≥ 78.\n"
            "Paste a CA for a live check, or tap 🔄 Rescan.",
            kicker="quality filter held the line",
        )
    lines = []
    for index, analysis in enumerate(candidates, 1):
        s = analysis.snapshot
        symbol = escape(s.symbol or "UNKNOWN")
        crown = "🏆 " if index == 1 else ""
        lines.append(
            f"{crown}{_score_emoji(analysis.degen_score)} <b>{index}. ${symbol}</b> · {_chain_badge(s.chain)}\n"
            f"{bar(analysis.degen_score)} degen {analysis.degen_score}   ·   {compact(s.liquidity)} liq   ·   {_change(s.price_change_1h)} 1h\n"
            f"{_check_badges(analysis)}\n"
            f"<code>{sparkline(momentum_points(s))}</code>"
        )
    lines.append("\nDefault check ran on every pick (mint / holders / honeypot). Tap a card for the full scan.")
    return glass_card(
        f"🏆  Best degen · {escape(label)}",
        "\n\n".join(lines),
        kicker=f"top {len(candidates)} elite pick(s)",
        expandable=True,
    )


def _holders_block(scan) -> str:
    holders = getattr(scan, "top_holders", None) if scan is not None else None
    if not holders:
        return "👥 <b>Top holders</b>\nNo holder tape from this provider yet."
    lines = ["👥 <b>Top holders</b>"]
    for item in holders[:8]:
        addr = str(item.get("address") or "")
        short = f"<code>{addr[:4]}...{addr[-4:]}</code>" if len(addr) > 10 else f"<code>{addr or '?'}</code>"
        pct = item.get("pct")
        pct_txt = f"  {pct:.2f}%" if isinstance(pct, (int, float)) else ""
        lines.append(f"{short}{pct_txt}")
    return "\n".join(lines)


def candidate_text(analysis: CandidateAnalysis, prior_calls=None, price_history=None) -> str:
    s = analysis.snapshot
    symbol = escape(s.symbol or "UNKNOWN")
    name = escape(s.name or "Unknown token")
    positives = "\n".join(f"➕ {escape(x)}" for x in analysis.score.positive_signals) or "None from supplied data"
    negatives = "\n".join(f"➖ {escape(x)}" for x in analysis.score.negative_signals) or "None identified"
    reasons = "\n".join(f"• {escape(x)}" for x in analysis.filters.reasons) or "Passed configured filters"
    body = (
        f"🪙 <b>${symbol}</b> · {name}\n"
        f"{_chain_badge(s.chain)} · {escape(s.dex or 'unknown dex')} · ⏱ {age_text(s.pair_age_seconds)}\n"
        f"{_score_emoji(analysis.score.score)} {bar(analysis.score.score)} <b>{analysis.score.score}/100</b> ({escape(analysis.score.confidence)})\n"
        f"🎯 Alpha {bar(analysis.degen_score)} <b>{analysis.degen_score}/100</b>\n\n"
        f"{_chart_block(s)}\n\n"
        f"{deep_risk_block(analysis.deep_risk)}\n\n"
        f"{coin_scan_block(analysis.coin_scan, s)}\n\n"
        f"{_holders_block(analysis.coin_scan)}\n\n"
        f"{pump_after_call_block(prior_calls or [], s.price, price_history, s.market_cap)}\n\n"
        f"{_metrics(
            ('💵 Price', money(s.price)),
            ('🏦 Market cap', compact(s.market_cap)),
            ('💧 Liquidity', compact(s.liquidity)),
            ('📊 Volume 1H / 6H / 24H', f'{compact(s.volume_1h)} / {compact(s.volume_6h)} / {compact(s.volume_24h)}'),
            ('📈 Change 5m / 1H / 6H / 24H', f'{_change(s.price_change_m5)} / {_change(s.price_change_1h)} / {_change(s.price_change_6h)} / {_change(s.price_change_24h)}'),
            ('🔄 Buys / Sells', _pair(s.buys, s.sells, 'n/a')),
        )}\n\n"
        f"{_degen_block(analysis)}\n\n"
        f"✨ <b>Signals</b>\n{positives}\n\n"
        f"⚠️ <b>Negatives</b>\n{negatives}\n\n"
        f"🧪 <b>Filters</b>\n{reasons}\n\n"
        f"📄 Contract\n<code>{escape(s.contract_address)}</code>"
    )
    return glass_card(f"🪙📈  ${symbol}", body, kicker="live token + after-call pump", expandable=True)


def _call_scan_block(call) -> str:
    payload = getattr(call, "initial_snapshot", None)
    if isinstance(payload, dict) and isinstance(payload.get("coin_scan"), dict):
        try:
            return coin_scan_block(CoinScan.model_validate(payload["coin_scan"]))
        except Exception:
            return coin_scan_block(None)
    return coin_scan_block(None)


def call_text(call, live: CandidateAnalysis | None = None) -> str:
    symbol = escape(call.token.symbol or "UNKNOWN")
    marks = []
    for milestone in sorted(call.milestones, key=lambda item: item.target_multiple):
        flag = "✅ HIT" if milestone.status == "HIT" else "⏳ open"
        marks.append(f"{flag}  {milestone.target_multiple}X")
    milestone_block = "\n".join(marks) or "No milestones"
    status_icon = "🟢" if call.status == "ACTIVE" else "⚪️"
    current = call.current_price
    multiple = call.current_multiple
    scan_block = _call_scan_block(call)
    live_block = ""
    if live is not None:
        snap = live.snapshot
        if snap.price is not None and call.reference_price and call.reference_price > 0:
            current = snap.price
            multiple = current / call.reference_price
        scan_block = coin_scan_block(live.coin_scan, snap)
        live_block = f"\n\n{_chart_block(snap)}\n📡 Live 5m {_change(snap.price_change_m5)}  ·  1h {_change(snap.price_change_1h)}"
    trend = "🚀" if multiple >= 1 else "🧊"
    body = (
        f"{status_icon} {escape(call.status)} · {_chain_badge(call.token.chain)}\n"
        f"🪙 <b>${symbol}</b>\n"
        f"{trend} Pump since call  <b>{multiple:.2f}X</b>  ({_pump_percent(multiple)})\n\n"
        f"{_metrics(
            ('🔒 Reference', money(call.reference_price)),
            ('💵 Current', money(current)),
            ('🏆 Observed ATH', f'{call.highest_multiple:.2f}X'),
        )}\n\n"
        f"{scan_block}{live_block}\n\n"
        f"🎯 <b>Milestones</b>\n{milestone_block}\n\n"
        f"📄 Contract\n<code>{escape(call.token.contract_address)}</code>"
    )
    return glass_card(f"📌🚀  Call #{call.id}", body, kicker="paper position · after-call pump", expandable=True)


def milestone_text(call, milestone, multiple: Decimal, extra: str = "") -> str:
    symbol = escape(call.token.symbol or "UNKNOWN")
    details = f"\n{extra.strip()}" if extra.strip() else ""
    body = (
        f"💥🎯 <b>{milestone.target_multiple}X SMASHED</b>\n"
        f"🪙 <b>${symbol}</b> · {_chain_badge(getattr(call.token, 'chain', None))}\n"
        f"🚀 Pump since call  <b>{multiple:.2f}X</b>  ({_pump_percent(multiple)})\n\n"
        f"{_metrics(
            ('🔒 Reference', money(call.reference_price)),
            ('✅ Hit price', money(milestone.hit_price)),
            ('📈 Multiple', f'{multiple:.2f}X'),
        )}{details}\n\n"
        f"Price crossed {milestone.target_multiple}X vs the locked reference. One-time alert."
    )
    return glass_card("🎯💥  MILESTONE HIT", body, kicker="one-time cross · paper only")


def recovery_alert_text(call) -> str:
    symbol = escape(call.token.symbol or "UNKNOWN")
    body = (
        f"🪙 <b>${symbol}</b> · {_chain_badge(call.token.chain)}\n"
        f"📌 Call #{call.id} recovered after a restart\n\n"
        f"{_metrics(
            ('🔒 Reference price', money(call.reference_price)),
            ('🎯 Initial score', f'{call.initial_score}/100'),
            ('🛡 Risk', _risk_badge(call.initial_risk)),
        )}\n\n"
        "📡 Tracking is active. Research and paper-tracking alert; this does not guarantee future performance."
    )
    return glass_card("🚨♻️  MARKET ALERT", body, kicker="recovered unsent call")


def scanning_text() -> str:
    return glass_card(
        "✨🎯  Hunting degens",
        "Reading live DexScreener + Gecko new/trending pools…\nKeeping only the best degen. Junk gets dropped.",
        kicker="in flight",
    )


def checking_text() -> str:
    return glass_card(
        "🔬  Default check",
        "Looking up the pair, then mint / freeze / holders / honeypot.",
        kicker="in flight",
    )


def not_found_text(kind: str = "Call") -> str:
    return glass_card(f"❔  {escape(kind)} not found", "Nothing in the desk matches that ID.\n⬅️ Back and try another card.", kicker="empty lookup")


def unavailable_text() -> str:
    return glass_card("🌫️  Token haze", "Token data is unavailable right now.\n⬅️ Back to the scan desk and try again.", kicker="provider miss")


def already_tracked_text() -> str:
    return glass_card("📌  Already tracking", "This token already has an active paper call.\nOpen 📌 Active to view the after-call pump.", kicker="duplicate guard")


def need_price_text() -> str:
    return glass_card("💵  No price", "A valid current price is required before tracking.", kicker="blocked")


def lookup_miss_text() -> str:
    return glass_card(
        "🔎  No pair",
        "No market pair found for that contract or DexScreener URL on Solana, Ethereum, BNB, or Base.",
        kicker="lookup miss",
    )


def close_prompt_suffix() -> str:
    return "\n\n<b>🛑 Close this paper call?</b>\n<i>Reference price, ATH, and after-call pump stay on the tape.</i>"


def call_usage() -> str:
    return glass_card("📌  Open a call", "Usage: <code>/call ID</code>\nExample: <code>/call 12</code>", kicker="command hint")


def close_usage() -> str:
    return glass_card("🛑  Close a call", "Usage: <code>/close ID</code>\nExample: <code>/close 12</code>", kicker="command hint")


def chains_text(enabled: tuple[str, ...] | list[str]) -> str:
    lines = []
    for name, label in (("solana", "🟣 Solana"), ("base", "🔵 Base"), ("ethereum", "💠 Ethereum"), ("bsc", "🟡 BNB")):
        mark = "✅ ON" if name in enabled else "⚪️ OFF"
        lines.append(f"{label}  ·  {mark}")
    return glass_card(
        "🌐  Chains",
        "Official degen calls only fire on enabled chains.\nTap to toggle. At least one chain must stay on.\n\n" + "\n".join(lines),
        kicker="live override · Redis",
    )


def ca_usage() -> str:
    return glass_card(
        "🔬  Default check",
        "This desk always runs the coin scan by default.\n"
        "FluxRPC mint/freeze · Birdeye holders · RugCheck/GoPlus honeypot-tax-LP.\n\n"
        "Paste a CA now, or use <code>/ca CONTRACT</code>.\n"
        "Links are parsed for lookup, then the full report stays in this chat.",
        kicker="mint · holders · honeypot",
    )


def track_usage() -> str:
    return glass_card("📌  Track from NOW", "Usage: <code>/track CONTRACT</code>\nStarts a personal paper call at the live price.", kicker="command hint")
