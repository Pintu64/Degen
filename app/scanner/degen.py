from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.config import Settings
from app.domain import CandidateAnalysis, Chain, RiskLevel, RiskVerdict, TokenSnapshot
from app.scanner.risk_scan import on_pump_curve


def _homoglyph(symbol: str | None) -> bool:
    if not symbol:
        return False
    has_latin = any(ch.isascii() and ch.isalpha() for ch in symbol)
    has_lookalike = any((not ch.isascii()) and ch.isalpha() for ch in symbol)
    return has_latin and has_lookalike

COPYCAT = {"BTC", "ETH", "SOL", "WETH", "WBNB", "USDT", "USDC", "WBTC", "DAI", "BONK", "DOGE", "SHIB", "PEPE", "WIF"}

WINDOWS = {
    Chain.SOLANA: {"min_liq": Decimal("4000"), "max_liq": Decimal("150000"), "min_mc": Decimal("8000"), "max_mc": Decimal("400000")},
    Chain.BASE: {"min_liq": Decimal("3000"), "max_liq": Decimal("120000"), "min_mc": Decimal("6000"), "max_mc": Decimal("300000")},
    Chain.ETHEREUM: {"min_liq": Decimal("8000"), "max_liq": Decimal("200000"), "min_mc": Decimal("15000"), "max_mc": Decimal("500000")},
    Chain.BSC: {"min_liq": Decimal("3000"), "max_liq": Decimal("120000"), "min_mc": Decimal("6000"), "max_mc": Decimal("300000")},
}


@dataclass(frozen=True)
class DegenRating:
    score: int
    reasons: list[str]
    too_late: bool
    eligible: bool
    rejections: list[str]
    tier: str


def degen_tier(score: int) -> str:
    if score >= 90:
        return "S+"
    if score >= 85:
        return "A"
    if score >= 78:
        return "B"
    return "F"


class DegenRanker:
    """Accuracy over volume. Pre-filter, then alpha. Official call still needs deep-risk PASS."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _window(self, chain: Chain) -> dict[str, Decimal]:
        return WINDOWS.get(chain, WINDOWS[Chain.SOLANA])

    def _already_vertical(self, snapshot: TokenSnapshot) -> bool:
        for change in (snapshot.price_change_24h, snapshot.price_change_6h, snapshot.price_change_1h):
            if change is not None and change >= self.settings.max_degen_24h_change_percent:
                return True
        return False

    def _hard_filters(self, snapshot: TokenSnapshot) -> list[str]:
        fails: list[str] = []
        window = self._window(snapshot.chain)
        liq = snapshot.liquidity
        mc = snapshot.market_cap
        age = snapshot.pair_age_seconds
        if snapshot.price is None or snapshot.price <= 0:
            fails.append("No valid price")
        if liq is None:
            fails.append("No liquidity")
        elif liq < window["min_liq"]:
            fails.append("Liquidity too thin")
        elif liq > window["max_liq"]:
            fails.append("Liquidity already cooked")
        if mc is None:
            fails.append("No market cap")
        elif mc < window["min_mc"]:
            fails.append("Market cap too small")
        elif mc > window["max_mc"]:
            fails.append("Market cap too large for a fresh degen")
        if mc is not None and liq is not None and liq > 0:
            ratio = mc / liq
            if ratio < Decimal("0.8"):
                fails.append("MC/LP too low")
            elif ratio > Decimal("15"):
                fails.append("MC/LP too high — exit liquidity risk")
        if age is not None:
            if age < self.settings.min_degen_pair_age_seconds:
                fails.append("Pair too fresh — rug window")
            elif age > 86400:
                fails.append("Pair older than 24h")
            elif age > 60 and snapshot.volume_m5 == 0 and snapshot.volume_24h is not None and snapshot.volume_24h <= 0:
                fails.append("Near-zero volume after first minute")
        ticker = (snapshot.symbol or "").upper()
        if ticker in COPYCAT:
            fails.append("Copycat ticker of a major coin")
        if _homoglyph(snapshot.symbol):
            fails.append("Homoglyph / unicode ticker")
        if snapshot.buy_tax is not None and snapshot.buy_tax > 8:
            fails.append("High buy tax")
        if snapshot.sell_tax is not None and snapshot.sell_tax > 8:
            fails.append("High sell tax")
        return fails

    def _alpha(self, analysis: CandidateAnalysis) -> tuple[int, list[str], dict[str, int]]:
        snap = analysis.snapshot
        scan = analysis.coin_scan
        reasons: list[str] = []
        momentum = structure = liquidity = holders = narrative = confirm = 0

        if snap.price_change_m5 is not None and snap.price_change_m5 > 0:
            momentum += 8
            reasons.append("5m heat is green")
        if snap.price_change_1h is not None:
            change = snap.price_change_1h
            if Decimal("3") <= change <= Decimal("80"):
                momentum += 10
                reasons.append("Healthy 1h momentum, not a finished candle")
            elif change > Decimal("120"):
                momentum = max(0, momentum - 8)
                reasons.append("1h already parabolic")
        buys = snap.buys_m5 if snap.buys_m5 is not None else snap.buys
        sells = snap.sells_m5 if snap.sells_m5 is not None else snap.sells
        if buys is not None and sells is not None and sells >= 0 and buys > sells:
            momentum += 10
            reasons.append("Buy pressure beating sells")
        momentum = min(28, momentum)

        dumped = snap.price_change_1h is not None and snap.price_change_1h <= Decimal("-60")
        if not dumped:
            structure += 10
        if snap.price_change_m5 is not None and snap.price_change_1h is not None and snap.price_change_m5 > 0 and snap.price_change_1h > 0:
            structure += 8
            reasons.append("5m and 1h both printing up")
        structure = min(18, structure)

        mc, liq = snap.market_cap, snap.liquidity
        if mc is not None and liq is not None and liq > 0:
            ratio = mc / liq
            if Decimal("2") <= ratio <= Decimal("5"):
                liquidity += 10
                reasons.append(f"MC/LP {ratio:.1f} sits in the call zone")
            elif Decimal("1.3") <= ratio <= Decimal("7"):
                liquidity += 6
        if scan and scan.lp_locked:
            liquidity += 4
            reasons.append("LP locked or burned")
        elif on_pump_curve(snap):
            liquidity += 3
        liquidity = min(14, liquidity)

        top10 = (scan.top10_percent if scan and scan.top10_percent is not None else snap.top_holder_percentage)
        if top10 is not None:
            if top10 <= 25:
                holders += 16
                reasons.append("Holder distribution clean")
            elif top10 <= 35:
                holders += 10
                reasons.append("Holder distribution inside range")
            elif top10 <= 45:
                holders += 4
        else:
            holders += 6
        holders = min(16, holders)

        age = snap.pair_age_seconds
        if age is not None and 180 <= age <= self.settings.preferred_degen_pair_age_seconds:
            narrative += 8
            reasons.append("Age is in the 3–75m degen window")
        elif age is not None and self.settings.min_degen_pair_age_seconds <= age <= self.settings.max_degen_pair_age_seconds:
            narrative += 4
        ticker = (snap.symbol or "").upper()
        if ticker and ticker not in COPYCAT:
            narrative += 4
        if snap.boosted and top10 is not None and top10 <= 35 and buys and sells and buys > sells:
            narrative += 0
            reasons.append("Boost only counts with clean holders + real buys")
        narrative = min(12, narrative)

        known = sum(1 for item in (snap.price, snap.market_cap, snap.liquidity, snap.volume_24h) if item is not None)
        if known >= 4:
            confirm += 8
        elif known >= 2:
            confirm += 4
        if scan and scan.source not in {"none", "error", ""}:
            confirm += 4
        confirm = min(12, confirm)

        score = momentum + structure + liquidity + holders + narrative + confirm
        if snap.price_change_24h is not None and Decimal("150") <= snap.price_change_24h < self.settings.max_degen_24h_change_percent:
            score -= 12
            reasons.append("Already +150–250% from open")
        if top10 is not None and top10 > 35:
            score -= 20
            reasons.append("Residual bundle / top10 heavy")
        if analysis.risk.level == RiskLevel.HIGH:
            score -= 10
        flags = (scan.flags if scan else None) or snap.suspicious_flags
        if any("mutable" in str(flag).lower() for flag in flags):
            score -= 10
        if snap.volume_24h is not None and mc is not None and mc > 0 and snap.volume_24h > mc * 8:
            if snap.price_change_1h is not None and abs(snap.price_change_1h) < 5:
                score -= 15
                reasons.append("Volume looks inorganic")
        score = max(0, min(100, score))
        analysis.alpha = {
            "momentum": momentum,
            "structure": structure,
            "liquidity": liquidity,
            "holders": holders,
            "narrative": narrative,
            "confirm": confirm,
        }
        return score, list(dict.fromkeys(reasons)), analysis.alpha

    def prefilter_ok(self, analysis: CandidateAnalysis) -> bool:
        return not self._hard_filters(analysis.snapshot) and not self._already_vertical(analysis.snapshot)

    def may_call(self, analysis: CandidateAnalysis) -> bool:
        if not self.prefilter_ok(analysis):
            return False
        report = analysis.deep_risk
        if report is None or report.verdict == RiskVerdict.UNSCANNED:
            return False
        if report.verdict == RiskVerdict.FAIL:
            return False
        if report.verdict == RiskVerdict.PASS_WITH_WARN:
            return analysis.degen_score >= self.settings.warn_call_score
        return analysis.degen_score >= self.settings.min_score

    def rate(self, analysis: CandidateAnalysis) -> DegenRating:
        snapshot = analysis.snapshot
        too_late = self._already_vertical(snapshot)
        rejections = self._hard_filters(snapshot)
        if too_late:
            rejections.append("Already +250% — too late")
        score, reasons, _ = self._alpha(analysis)
        eligible = (
            not rejections
            and not too_late
            and snapshot.price is not None
            and snapshot.price > 0
            and score >= self.settings.min_score
            and analysis.risk.level != RiskLevel.HIGH
        )
        if eligible:
            reasons.insert(0, "Passed every hard degen filter")
        return DegenRating(
            score=score,
            reasons=reasons or rejections,
            too_late=too_late,
            eligible=eligible,
            rejections=list(dict.fromkeys(rejections)),
            tier=degen_tier(score),
        )

    def apply(self, analysis: CandidateAnalysis) -> CandidateAnalysis:
        rating = self.rate(analysis)
        analysis.degen_score = rating.score
        analysis.degen_reasons = rating.reasons or rating.rejections
        analysis.too_late = rating.too_late
        return analysis

    def select_best(self, candidates: list[CandidateAnalysis], limit: int | None = None) -> list[CandidateAnalysis]:
        cap = limit if limit is not None else self.settings.max_degen_picks
        priced = [
            item for item in candidates
            if item.snapshot.price is not None and item.snapshot.price > 0
        ]
        window = [item for item in priced if self.prefilter_ok(item)]
        pool = window or [
            item for item in priced
            if not item.too_late and (item.snapshot.symbol or "").upper() not in COPYCAT
        ]
        pool.sort(key=lambda item: (item.degen_score, item.score.score, item.snapshot.volume_24h or 0), reverse=True)
        preferred = [item for item in pool if item.snapshot.chain in {Chain.SOLANA, Chain.BASE}]
        rest = [item for item in pool if item not in preferred]
        ordered = preferred + rest
        if not ordered or cap <= 0:
            return []
        return ordered[: max(0, cap)]
