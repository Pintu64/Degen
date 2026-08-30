from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from app.bot.charts import gmgn_url, rugcheck_url
from app.domain import CandidateAnalysis, Chain

CHAIN_SHORT = {Chain.SOLANA: "sol", Chain.ETHEREUM: "eth", Chain.BSC: "bsc", Chain.BASE: "base"}
SHORT_CHAIN = {value: key for key, value in CHAIN_SHORT.items()}

NAV_LABELS = {
    "🔎 Scan": "scan",
    "🎯 Best": "best",
    "🔬 Check": "check",
    "📡 Status": "status",
    "📌 Active": "active",
    "📚 History": "history",
    "📊 Stats": "stats",
    "⚙️ Settings": "settings",
    "❓ Help": "help",
    "Scan": "scan",
    "Best": "best",
    "Check": "check",
    "Status": "status",
    "Active": "active",
    "History": "history",
    "Stats": "stats",
    "Settings": "settings",
    "Help": "help",
}


def _btn(text: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback)


def _back_row(*extra: InlineKeyboardButton, back: str = "nav:home") -> list[InlineKeyboardButton]:
    row = [_btn("⬅️ Back", back)]
    row.extend(extra)
    return row


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 Best"), KeyboardButton(text="🔬 Check")],
            [KeyboardButton(text="🔎 Scan"), KeyboardButton(text="📡 Status")],
            [KeyboardButton(text="📌 Active"), KeyboardButton(text="📚 History")],
            [KeyboardButton(text="📊 Stats"), KeyboardButton(text="⚙️ Settings")],
            [KeyboardButton(text="❓ Help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def home_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("🏆 Best degen", "scan:best"),
            _btn("🔬 Check CA", "nav:check"),
        ],
        [
            _btn("🌐 Scan all", "scan:all"),
        ],
        [
            _btn("🟣 Solana", "scan:sol"),
            _btn("💠 Ethereum", "scan:eth"),
        ],
        [
            _btn("🟡 BNB", "scan:bsc"),
            _btn("🔵 Base", "scan:base"),
        ],
        [
            _btn("📌 Active", "nav:active"),
            _btn("📚 History", "nav:history"),
        ],
        [
            _btn("📊 Stats", "nav:stats"),
            _btn("🌐 Chains", "nav:chains"),
        ],
        [
            _btn("⚙️ Settings", "nav:settings"),
        ],
    ])


def scan_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🏆 Best degen", "scan:best"), _btn("🌐 All chains", "scan:all")],
        [
            _btn("🟣 Solana", "scan:sol"),
            _btn("💠 Ethereum", "scan:eth"),
        ],
        [
            _btn("🟡 BNB", "scan:bsc"),
            _btn("🔵 Base", "scan:base"),
        ],
        _back_row(),
    ])


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _back_row(_btn("🔎 Scan", "nav:scan"), _btn("📌 Active", "nav:active")),
    ])


def status_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Refresh", "nav:status")],
        _back_row(),
    ])


def stats_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Refresh", "nav:stats")],
        _back_row(),
    ])


def chains_inline(enabled: tuple[str, ...] | list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for chain, label in (
        (Chain.SOLANA, "🟣 Solana"),
        (Chain.BASE, "🔵 Base"),
        (Chain.ETHEREUM, "💠 Ethereum"),
        (Chain.BSC, "🟡 BNB"),
    ):
        mark = "✅" if chain.value in enabled else "⚪️"
        rows.append([_btn(f"{mark} {label}", f"chain:{chain.value}")])
    rows.append(_back_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Refresh", "nav:settings")],
        _back_row(),
    ])


def scan_results_inline(candidates: list[CandidateAnalysis], scan_key: str = "all") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, analysis in enumerate(candidates[:8], 1):
        snapshot = analysis.snapshot
        short = CHAIN_SHORT[snapshot.chain]
        symbol = (snapshot.symbol or "TOKEN")[:12]
        crown = "🏆 " if index == 1 else ""
        rows.append([_btn(
            f"{crown}{index}. ${symbol} · {analysis.degen_score}",
            f"v:{short}:{snapshot.contract_address}",
        )])
    rows.append(_back_row(_btn("🔄 Rescan", f"scan:{scan_key}"), back="nav:scan"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _trade_row(chain: Chain, address: str, pair_address: str | None = None) -> list[InlineKeyboardButton]:
    dex = f"https://dexscreener.com/{chain.value}/{pair_address or address}"
    return [
        InlineKeyboardButton(text="📈 DEX", url=dex),
        InlineKeyboardButton(text="🧬 GMGN", url=gmgn_url(chain, address)),
        InlineKeyboardButton(text="🛡 SAFETY", url=rugcheck_url(chain, address)),
    ]


def token_inline(
    chain: Chain,
    address: str,
    chart_url: str | None = None,
    explorer_url: str | None = None,
    back: str = "nav:scan",
    pair_address: str | None = None,
) -> InlineKeyboardMarkup:
    short = CHAIN_SHORT[chain]
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📌 Track this CA", f"t:{short}:{address}"), _btn("🔄 Refresh", f"v:{short}:{address}")],
        _trade_row(chain, address, pair_address),
        _back_row(back=back),
    ])


def call_inline(
    call_id: int,
    chart_url: str | None = None,
    active: bool = True,
    chain: Chain | None = None,
    address: str | None = None,
    pair_address: str | None = None,
) -> InlineKeyboardMarkup:
    back = "nav:active" if active else "nav:history"
    rows: list[list[InlineKeyboardButton]] = [[
        _btn("🔄 Refresh", f"c:{call_id}"),
        _btn("📌 Active", "nav:active"),
    ]]
    if active:
        rows.append([_btn("🛑 Close call", f"x:{call_id}")])
    rows.append(_back_row(back=back))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def close_confirm_inline(call_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Confirm close", f"z:{call_id}")],
        _back_row(back=f"c:{call_id}"),
    ])


def calls_inline(calls, prefix: str = "c", back: str = "nav:home") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for call in calls[:20]:
        symbol = (call.token.symbol or "TOKEN")[:10]
        trend = "🚀" if call.current_multiple >= 1 else "🧊"
        rows.append([_btn(
            f"{trend} #{call.id} ${symbol} {call.current_multiple:.2f}X",
            f"{prefix}:{call.id}",
        )])
    rows.append(_back_row(_btn("🔎 Scan", "nav:scan"), back=back))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_buttons(
    call_id: int,
    chart_url: str | None = None,
    chain: Chain | str | None = None,
    address: str | None = None,
    pair_address: str | None = None,
) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = [[{"text": "📌 Open call", "callback": f"c:{call_id}"}]]
    resolved = Chain(chain) if isinstance(chain, str) else chain
    if resolved is not None and address:
        dex = f"https://dexscreener.com/{resolved.value}/{pair_address or address}"
        rows.append([
            {"text": "📈 DEX", "url": dex},
            {"text": "🧬 GMGN", "url": gmgn_url(resolved, address)},
            {"text": "🛡 SAFETY", "url": rugcheck_url(resolved, address)},
        ])
    rows.append([{"text": "⬅️ Back", "callback": "nav:home"}, {"text": "📌 Active", "callback": "nav:active"}])
    return rows


def from_payload(buttons: list | None) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    keyboard: list[list[InlineKeyboardButton]] = []
    for row in buttons:
        if not isinstance(row, list):
            continue
        rendered: list[InlineKeyboardButton] = []
        for item in row:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
                continue
            text = item["text"][:64]
            url = item.get("url")
            callback = item.get("callback")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                rendered.append(InlineKeyboardButton(text=text, url=url))
            elif isinstance(callback, str) and len(callback.encode("utf-8")) <= 64:
                rendered.append(InlineKeyboardButton(text=text, callback_data=callback))
        if rendered:
            keyboard.append(rendered)
    return InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None
