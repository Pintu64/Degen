from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import quote

from app.domain import Chain, TokenSnapshot

GECKO_NETWORK = {
    Chain.SOLANA: "solana",
    Chain.ETHEREUM: "eth",
    Chain.BSC: "bsc",
    Chain.BASE: "base",
}

DEXTOOLS_CHAIN = {
    Chain.SOLANA: "solana",
    Chain.ETHEREUM: "ether",
    Chain.BSC: "bnb",
    Chain.BASE: "base",
}

BIRDEYE_CHAIN = {
    Chain.SOLANA: "solana",
    Chain.ETHEREUM: "ethereum",
    Chain.BSC: "bsc",
    Chain.BASE: "base",
}

_SPARK = "▁▂▃▄▅▆▇█"


def gecko_url(chain: Chain, address: str) -> str:
    return f"https://www.geckoterminal.com/{GECKO_NETWORK[chain]}/tokens/{address}"


def dextools_url(chain: Chain, pair_address: str | None) -> str | None:
    if not pair_address:
        return None
    return f"https://www.dextools.io/app/en/{DEXTOOLS_CHAIN[chain]}/pair-explorer/{pair_address}"


def birdeye_url(chain: Chain, address: str) -> str:
    return f"https://birdeye.so/token/{address}?chain={BIRDEYE_CHAIN[chain]}"


GMGN_CHAIN = {
    Chain.SOLANA: "sol",
    Chain.ETHEREUM: "eth",
    Chain.BSC: "bsc",
    Chain.BASE: "base",
}


def gmgn_url(chain: Chain, address: str) -> str:
    return f"https://gmgn.ai/{GMGN_CHAIN[chain]}/token/{address}"


def gecko_pool_url(chain: Chain, pair_address: str | None) -> str | None:
    if not pair_address:
        return None
    return f"https://www.geckoterminal.com/{GECKO_NETWORK[chain]}/pools/{pair_address}"


def dex_embed_url(chain: Chain, pair_address: str | None) -> str | None:
    if not pair_address:
        return None
    tf = "1" if False else "5"
    return f"https://dexscreener.com/{chain.value}/{pair_address}?embed=1&theme=dark&trades=0&info=0&chartInterval={tf}"


def rugcheck_url(chain: Chain, address: str) -> str:
    if chain == Chain.SOLANA:
        return f"https://rugcheck.xyz/tokens/{address}"
    chain_id = {Chain.ETHEREUM: "1", Chain.BSC: "56", Chain.BASE: "8453"}.get(chain, "1")
    return f"https://gopluslabs.io/token-security/{chain_id}/{address}"


def chart_image_url(snapshot: TokenSnapshot) -> str:
    points = momentum_points(snapshot) or [100.0]
    labels = ["24h", "6h", "1h", "5m", "now"][-len(points):]
    spec = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "data": [round(point, 6) for point in points],
                "borderColor": "#00ffa3",
                "backgroundColor": "rgba(0,255,163,0.16)",
                "fill": True,
                "pointRadius": 3,
                "tension": 0.35,
            }],
        },
        "options": {
            "plugins": {"legend": {"display": False}, "title": {"display": True, "text": f"{snapshot.symbol or 'TOKEN'} 5m tape", "color": "#d7ffe8"}},
            "scales": {
                "x": {"ticks": {"color": "#8aa"}, "grid": {"color": "rgba(255,255,255,0.06)"}},
                "y": {"ticks": {"color": "#8aa"}, "grid": {"color": "rgba(255,255,255,0.06)"}},
            },
        },
    }
    return "https://quickchart.io/chart?w=800&h=360&bkg=%2307110d&c=" + quote(json.dumps(spec, separators=(",", ":")))


def sparkline(values: list[Decimal | float | None], size: int = 8) -> str:
    numbers: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number and abs(number) != float("inf"):
            numbers.append(number)
    if len(numbers) < 2:
        return "·" * size
    if len(numbers) > size:
        step = (len(numbers) - 1) / (size - 1)
        sampled = [numbers[round(index * step)] for index in range(size)]
        numbers = sampled
    low, high = min(numbers), max(numbers)
    span = high - low or 1.0
    last = len(_SPARK) - 1
    return "".join(_SPARK[min(last, max(0, int(round((item - low) / span * last))))] for item in numbers)


def momentum_points(snapshot: TokenSnapshot) -> list[float]:
    now = 100.0

    def rewind(change: Decimal | None) -> float | None:
        if change is None or not change.is_finite():
            return None
        factor = 1.0 + float(change) / 100.0
        if factor <= 0:
            return None
        return now / factor

    points = [
        rewind(snapshot.price_change_24h),
        rewind(snapshot.price_change_6h),
        rewind(snapshot.price_change_1h),
        rewind(snapshot.price_change_m5),
        now,
    ]
    return [point for point in points if point is not None]


def pressure_bar(buys: int | None, sells: int | None, width: int = 8) -> str:
    if buys is None or sells is None or buys + sells <= 0:
        return "Data unavailable"
    total = buys + sells
    green = max(0, min(width, round(buys / total * width)))
    return ("🟩" * green) + ("🟥" * (width - green))
