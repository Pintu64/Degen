from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from time import monotonic

from app.bot.charts import GECKO_NETWORK, momentum_points
from app.bot.formatting import age_text, compact, money
from app.config import get_settings
from app.domain import CandidateAnalysis, TokenSnapshot

BG = (7, 17, 13)
PANEL = (14, 32, 26)
LINE = (0, 255, 163)
RED = (255, 77, 109)
MUTED = (138, 170, 160)
WHITE = (230, 255, 242)
GOLD = (255, 209, 102)
FILL = (0, 70, 48)
DARK = (8, 22, 17)
FONTS = [
    "C:\\Windows\\Fonts\\segoeui.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\calibri.ttf",
]
_BIRDEYE_OHLCV_COOLDOWN_UNTIL = 0.0


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _ok(value: bool | None) -> tuple[str, tuple[int, int, int]]:
    if value is True:
        return "OPEN / YES", RED
    if value is False:
        return "REVOKED / NO", LINE
    return "UNKNOWN", MUTED


async def fetch_ohlcv(snapshot: TokenSnapshot) -> list[float]:
    global _BIRDEYE_OHLCV_COOLDOWN_UNTIL
    settings = get_settings()
    timeout = httpx.Timeout(2.2, connect=0.8)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if settings.birdeye_api_key and monotonic() >= _BIRDEYE_OHLCV_COOLDOWN_UNTIL:
            try:
                response = await client.get(
                    f"{settings.birdeye_base_url.rstrip('/')}/defi/ohlcv",
                    params={"address": snapshot.contract_address, "type": "5m"},
                    headers={"X-API-KEY": settings.birdeye_api_key, "x-chain": snapshot.chain.value},
                )
                if response.status_code == 429:
                    _BIRDEYE_OHLCV_COOLDOWN_UNTIL = monotonic() + 45
                elif response.status_code == 200:
                    payload = response.json()
                    items = ((payload.get("data") or {}).get("items") if isinstance(payload, dict) else None) or []
                    closes = []
                    for item in items[-40:]:
                        if isinstance(item, dict):
                            close = item.get("c") or item.get("close")
                            if close is not None:
                                closes.append(float(close))
                    if len(closes) >= 2:
                        return closes
            except Exception:
                pass
        if snapshot.pair_address:
            try:
                network = GECKO_NETWORK.get(snapshot.chain, snapshot.chain.value)
                response = await client.get(
                    f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{snapshot.pair_address}/ohlcv/minute",
                    params={"aggregate": "5", "limit": "40"},
                )
                if response.status_code == 200:
                    payload = response.json()
                    rows = (((payload.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [])
                    closes = [float(row[4]) for row in rows if isinstance(row, list) and len(row) >= 5]
                    if len(closes) >= 2:
                        return closes
            except Exception:
                pass
    return momentum_points(snapshot) or [100.0]


def _score_bar(draw: ImageDraw.ImageDraw, x: int, y: int, score: int, color: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((x, y, x + 220, y + 14), 7, fill=(20, 40, 32))
    filled = max(4, int(220 * max(0, min(100, score)) / 100))
    draw.rounded_rectangle((x, y, x + filled, y + 14), 7, fill=color)


def render_report(analysis: CandidateAnalysis, prices: list[float] | None = None) -> bytes:
    snap = analysis.snapshot
    scan = analysis.coin_scan
    prices = prices or momentum_points(snap) or [100.0]
    image = Image.new("RGB", (900, 1400), BG)
    draw = ImageDraw.Draw(image)
    title = _font(34)
    body = _font(21)
    small = _font(17)
    symbol = snap.symbol or "TOKEN"
    draw.rounded_rectangle((20, 20, 880, 1380), 28, fill=PANEL)
    draw.text((48, 40), f"${symbol}  FULL IN-BOT REPORT", font=title, fill=WHITE)
    draw.text((48, 86), f"{snap.chain.value.upper()}  ·  {snap.dex or 'dex'}  ·  age {age_text(snap.pair_age_seconds)}  ·  no website", font=small, fill=MUTED)

    score = analysis.degen_score or analysis.score.score
    safety = scan.safety_score if scan and scan.safety_score is not None else None
    draw.text((48, 122), f"DEGEN {score}/100", font=body, fill=LINE)
    _score_bar(draw, 48, 154, score, LINE)
    if safety is not None:
        draw.text((320, 122), f"SAFETY {safety}/100", font=body, fill=GOLD)
        _score_bar(draw, 320, 154, safety, GOLD)

    chart = (48, 184, 852, 500)
    draw.rounded_rectangle(chart, 18, fill=DARK, outline=(20, 60, 45), width=2)
    if len(prices) >= 2:
        low, high = min(prices), max(prices)
        span = (high - low) or 1.0
        left, top, right, bottom = chart[0] + 16, chart[1] + 28, chart[2] - 16, chart[3] - 16
        width = right - left
        height = bottom - top
        pts = []
        for index, price in enumerate(prices):
            x = left + index * width / max(1, len(prices) - 1)
            y = bottom - ((price - low) / span) * height
            pts.append((x, y))
        draw.polygon([(left, bottom), *pts, (pts[-1][0], bottom)], fill=FILL)
        draw.line(pts, fill=LINE, width=3)
        last = prices[-1]
        change = ((prices[-1] / prices[0]) - 1) * 100 if prices[0] else 0
        draw.text((56, 192), f"5m tape  {last:.8g}   {change:+.1f}%", font=small, fill=MUTED)

    metrics = [
        ("Price", money(snap.price)),
        ("MC", compact(snap.market_cap)),
        ("LP", compact(snap.liquidity)),
        ("Vol 24h", compact(snap.volume_24h)),
        ("5m", f"{snap.price_change_m5}%" if snap.price_change_m5 is not None else "n/a"),
        ("1h", f"{snap.price_change_1h}%" if snap.price_change_1h is not None else "n/a"),
        ("Buys/Sells", f"{snap.buys if snap.buys is not None else '-'} / {snap.sells if snap.sells is not None else '-'}"),
        ("6h / 24h", f"{snap.price_change_6h}% / {snap.price_change_24h}%"),
    ]
    for index, (label, value) in enumerate(metrics):
        col, row = index % 2, index // 2
        x, y = 48 + col * 410, 516 + row * 42
        draw.rounded_rectangle((x, y, x + 390, y + 36), 10, fill=DARK)
        draw.text((x + 12, y + 8), f"{label}  {value}", font=small, fill=WHITE)

    y = 700
    draw.text((48, y), "DEFAULT CHECK  ·  mint freeze holders honeypot", font=body, fill=GOLD)
    y += 40
    mint_txt, mint_color = _ok(scan.mint_authority if scan else None)
    freeze_txt, freeze_color = _ok(scan.freeze_authority if scan else None)
    honey = "HONEYPOT" if scan and scan.honeypot else ("CLEAN" if scan and scan.honeypot is False else "UNKNOWN")
    honey_color = RED if scan and scan.honeypot else (LINE if scan and scan.honeypot is False else MUTED)
    rows = [
        ("Honeypot", honey, honey_color),
        ("Mint", mint_txt, mint_color),
        ("Freeze", freeze_txt, freeze_color),
        ("Owner", "RENOUNCED" if scan and scan.ownership_renounced else ("DEV CAN RUG" if scan and scan.ownership_renounced is False else "UNKNOWN"), GOLD),
        ("LP lock", "LOCKED" if scan and scan.lp_locked else ("UNLOCKED" if scan and scan.lp_locked is False else "UNKNOWN"), LINE),
        ("Tax", f"buy {scan.buy_tax if scan and scan.buy_tax is not None else 'n/a'} / sell {scan.sell_tax if scan and scan.sell_tax is not None else 'n/a'}", WHITE),
        ("Holders", f"{scan.holders:,}" if scan and scan.holders is not None else "n/a", WHITE),
        ("Top 10", f"{scan.top10_percent:.1f}%" if scan and scan.top10_percent is not None else "n/a", WHITE),
    ]
    for label, value, color in rows:
        draw.text((48, y), label, font=small, fill=MUTED)
        draw.text((220, y), str(value), font=body, fill=color)
        y += 32

    flags = (scan.flags if scan else None) or []
    if flags:
        draw.text((48, y), "FLAGS  " + " · ".join(str(item) for item in flags[:4]), font=small, fill=RED)
        y += 28
    reasons = analysis.degen_reasons[:3] if analysis.degen_reasons else []
    if reasons:
        draw.text((48, y), "WHY  " + " · ".join(reasons)[:70], font=small, fill=GOLD)
        y += 28

    y += 6
    draw.text((48, y), "TOP HOLDERS", font=body, fill=GOLD)
    y += 32
    holders = (scan.top_holders if scan else None) or []
    if not holders:
        draw.text((48, y), "Holder tape from FluxRPC lands here", font=small, fill=MUTED)
        y += 26
    for item in holders[:6]:
        addr = str(item.get("address") or "")
        short = f"{addr[:4]}...{addr[-4:]}" if len(addr) > 10 else addr or "?"
        pct = item.get("pct")
        pct_txt = f"{pct:.2f}%" if isinstance(pct, (int, float)) else ""
        draw.text((48, y), f"{short}   {pct_txt}", font=small, fill=WHITE)
        y += 24

    ca = snap.contract_address
    draw.text((48, 1320), ca[:52] + ("..." if len(ca) > 52 else ""), font=small, fill=MUTED)
    draw.text((48, 1348), "NFA  ·  DYOR  ·  chart + check stay in this chat", font=small, fill=MUTED)

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def build_report_png(analysis: CandidateAnalysis) -> bytes:
    prices = await fetch_ohlcv(analysis.snapshot)
    return render_report(analysis, prices)
