from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from app.domain import CandidateAnalysis, Chain

CHAIN_SHORT = {Chain.SOLANA: "sol", Chain.ETHEREUM: "eth", Chain.BSC: "bsc"}
SHORT_CHAIN = {value: key for key, value in CHAIN_SHORT.items()}

NAV_LABELS = {
    "Scan": "scan",
    "Status": "status",
    "Active": "active",
    "History": "history",
    "Stats": "stats",
    "Settings": "settings",
    "Help": "help",
}


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Scan"), KeyboardButton(text="Status")],
            [KeyboardButton(text="Active"), KeyboardButton(text="History")],
            [KeyboardButton(text="Stats"), KeyboardButton(text="Settings")],
            [KeyboardButton(text="Help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def home_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Scan all", callback_data="scan:all"),
            InlineKeyboardButton(text="Status", callback_data="nav:status"),
        ],
        [
            InlineKeyboardButton(text="Solana", callback_data="scan:sol"),
            InlineKeyboardButton(text="Ethereum", callback_data="scan:eth"),
            InlineKeyboardButton(text="BNB", callback_data="scan:bsc"),
        ],
        [
            InlineKeyboardButton(text="Active", callback_data="nav:active"),
            InlineKeyboardButton(text="History", callback_data="nav:history"),
        ],
        [
            InlineKeyboardButton(text="Stats", callback_data="nav:stats"),
            InlineKeyboardButton(text="Settings", callback_data="nav:settings"),
        ],
    ])


def scan_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="All chains", callback_data="scan:all"),
        ],
        [
            InlineKeyboardButton(text="Solana", callback_data="scan:sol"),
            InlineKeyboardButton(text="Ethereum", callback_data="scan:eth"),
            InlineKeyboardButton(text="BNB", callback_data="scan:bsc"),
        ],
        [InlineKeyboardButton(text="Home", callback_data="nav:home")],
    ])


def back_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Scan", callback_data="scan:all"),
            InlineKeyboardButton(text="Active", callback_data="nav:active"),
            InlineKeyboardButton(text="Home", callback_data="nav:home"),
        ]
    ])


def settings_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Refresh", callback_data="nav:settings")],
        [InlineKeyboardButton(text="Home", callback_data="nav:home")],
    ])


def scan_results_inline(candidates: list[CandidateAnalysis]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, analysis in enumerate(candidates[:8], 1):
        snapshot = analysis.snapshot
        short = CHAIN_SHORT[snapshot.chain]
        symbol = (snapshot.symbol or "TOKEN")[:12]
        rows.append([InlineKeyboardButton(
            text=f"{index}. ${symbol} {analysis.score.score}/100",
            callback_data=f"v:{short}:{snapshot.contract_address}",
        )])
    rows.append([
        InlineKeyboardButton(text="Rescan", callback_data="scan:all"),
        InlineKeyboardButton(text="Home", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def token_inline(chain: Chain, address: str, chart_url: str | None = None, explorer_url: str | None = None) -> InlineKeyboardMarkup:
    short = CHAIN_SHORT[chain]
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="Track", callback_data=f"t:{short}:{address}"),
        InlineKeyboardButton(text="Refresh", callback_data=f"v:{short}:{address}"),
    ]]
    links: list[InlineKeyboardButton] = []
    if chart_url:
        links.append(InlineKeyboardButton(text="Chart", url=str(chart_url)))
    if explorer_url:
        links.append(InlineKeyboardButton(text="Explorer", url=explorer_url))
    if links:
        rows.append(links)
    rows.append([
        InlineKeyboardButton(text="Scan", callback_data="scan:all"),
        InlineKeyboardButton(text="Home", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def call_inline(call_id: int, chart_url: str | None = None, active: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(text="Refresh", callback_data=f"c:{call_id}"),
        InlineKeyboardButton(text="Active", callback_data="nav:active"),
    ]]
    if chart_url:
        rows.append([InlineKeyboardButton(text="Chart", url=str(chart_url))])
    if active:
        rows.append([InlineKeyboardButton(text="Close call", callback_data=f"x:{call_id}")])
    rows.append([InlineKeyboardButton(text="Home", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def close_confirm_inline(call_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Confirm close", callback_data=f"z:{call_id}"),
        InlineKeyboardButton(text="Cancel", callback_data=f"c:{call_id}"),
    ]])


def calls_inline(calls, prefix: str = "c") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for call in calls[:20]:
        symbol = (call.token.symbol or "TOKEN")[:10]
        rows.append([InlineKeyboardButton(
            text=f"#{call.id} ${symbol} {call.current_multiple:.2f}X",
            callback_data=f"{prefix}:{call.id}",
        )])
    rows.append([
        InlineKeyboardButton(text="Scan", callback_data="scan:all"),
        InlineKeyboardButton(text="Home", callback_data="nav:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def alert_buttons(call_id: int, chart_url: str | None = None) -> list[list[dict[str, str]]]:
    row = [{"text": "Open call", "callback": f"c:{call_id}"}]
    if chart_url:
        row.append({"text": "Chart", "url": str(chart_url)})
    return [row, [{"text": "Active", "callback": "nav:active"}]]


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
