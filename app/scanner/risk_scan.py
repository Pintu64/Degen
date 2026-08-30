from __future__ import annotations

from decimal import Decimal

from app.domain import (
    CandidateAnalysis,
    Chain,
    DeepRiskReport,
    RiskCheck,
    RiskVerdict,
    TokenSnapshot,
)

SAFE_QUOTES = {"SOL", "WSOL", "ETH", "WETH", "USDC", "USDT", "USD1", "BNB", "WBNB", "CBETH"}
PUMP_MARKERS = ("pumpfun", "pumpswap")
POST_MIGRATE = ("raydium", "meteora", "orca", "moonshot")
TOKEN2022_FAIL = (
    "transfer fee",
    "permanent delegate",
    "confidential",
    "anti-transfer",
    "transfer hook",
    "non-transferable",
    "fee-on-transfer",
)


def on_pump_curve(snapshot: TokenSnapshot) -> bool:
    dex = (snapshot.dex or "").lower()
    if any(marker in dex for marker in POST_MIGRATE):
        return False
    return any(marker in dex for marker in PUMP_MARKERS)


def _check(name: str, result: str, evidence: str = "", critical: bool = False) -> RiskCheck:
    return RiskCheck(name=name, result=result, evidence=evidence, critical=critical)


def evaluate_deep_risk(analysis: CandidateAnalysis) -> DeepRiskReport:
    snap = analysis.snapshot
    scan = analysis.coin_scan
    checks: list[RiskCheck] = []
    critical: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, str] = {}

    def fail(name: str, why: str) -> None:
        checks.append(_check(name, "FAIL", why, True))
        critical.append(why)
        evidence[name] = why

    def warn(name: str, why: str) -> None:
        checks.append(_check(name, "WARN", why))
        warnings.append(why)
        evidence[name] = why

    def ok(name: str, why: str) -> None:
        checks.append(_check(name, "PASS", why))
        evidence[name] = why

    symbol = snap.symbol or ""
    if symbol and any(not (ch.isascii() and (ch.isalnum() or ch in "._$")) for ch in symbol):
        fail("identity", f"Homoglyph / unicode ticker ${symbol}")
    quote = (snap.quote_symbol or "").upper()
    if quote and quote not in SAFE_QUOTES:
        fail("quote", f"Unsupported quote {quote}")
    elif quote:
        ok("quote", f"Quote {quote}")

    pump = on_pump_curve(snap)
    mint = scan.mint_authority if scan else snap.mint_authority
    freeze = scan.freeze_authority if scan else snap.freeze_authority
    if freeze is True and not pump:
        fail("freeze", "Freeze authority still open")
    elif freeze is True and pump:
        warn("freeze", "Freeze still open on Pump curve")
    elif freeze is False:
        ok("freeze", "Freeze revoked")
    else:
        warn("freeze", "Freeze authority unknown")

    if mint is True and not pump:
        fail("mint", "Mint authority still open")
    elif mint is True and pump:
        warn("mint", "Mint still on Pump.fun curve — migrate path")
    elif mint is False:
        ok("mint", "Mint revoked")
    else:
        warn("mint", "Mint authority unknown")

    honey = scan.honeypot if scan else None
    if honey is True:
        fail("honeypot", "Honeypot / cannot sell")
    elif honey is False:
        ok("honeypot", "Sell path clean")
    else:
        warn("honeypot", "Honeypot sim unknown")

    if scan and scan.rugged:
        fail("rugged", "Marked rugged")
    if scan and scan.blacklist:
        fail("blacklist", "Blacklist / whitelist trading still on")

    buy = scan.buy_tax if scan and scan.buy_tax is not None else snap.buy_tax
    sell = scan.sell_tax if scan and scan.sell_tax is not None else snap.sell_tax
    for label, tax in (("buy_tax", buy), ("sell_tax", sell)):
        if tax is None:
            continue
        if tax > 8:
            fail("tax", f"{label} {tax}% > 8%")
        elif tax >= 3:
            warn("tax", f"{label} {tax}% (soft)")
        else:
            ok("tax", f"{label} {tax}%")

    if snap.chain.is_evm:
        verified = scan.verified if scan and scan.verified is not None else snap.contract_verified
        if verified is False:
            fail("verified", "Unverified EVM source")
        elif verified is True:
            ok("verified", "Source verified")
        else:
            warn("verified", "Verification unknown")
        if scan and scan.proxy:
            fail("proxy", "Live proxy admin")
        owner = scan.ownership_renounced if scan else snap.ownership_renounced
        if owner is False and mint is True:
            fail("owner", "Owner can still mint")
        elif owner is False:
            warn("owner", "Owner not renounced")
        elif owner is True:
            ok("owner", "Ownership renounced")

    top10 = scan.top10_percent if scan and scan.top10_percent is not None else snap.top_holder_percentage
    if top10 is not None:
        evidence["top10"] = f"{top10:.1f}%"
        if top10 > 45:
            fail("holders", f"Top10 ex-LP {top10:.1f}% > 45%")
        elif top10 > 35:
            warn("holders", f"Top10 {top10:.1f}% heavy (35–45%)")
        else:
            ok("holders", f"Top10 {top10:.1f}%")
    else:
        warn("holders", "Top10 unknown")

    lp = scan.lp_locked if scan else None
    if pump:
        ok("lp", "Pump curve LP")
    elif lp is True:
        ok("lp", f"LP locked/burned {scan.lp_locked_percent if scan else ''}".strip())
    elif lp is False:
        fail("lp", "LP unlocked in deployer/EOA")
    else:
        warn("lp", "LP lock unknown")

    flags = list((scan.flags if scan else None) or snap.suspicious_flags or [])
    for flag in flags:
        lowered = flag.lower()
        if any(needle in lowered for needle in TOKEN2022_FAIL):
            fail("token2022", flag)
        elif "mutable" in lowered or "update authority" in lowered:
            warn("metadata", flag)

    if snap.boosted and (top10 is None or top10 > 35):
        warn("boost", "Dex boost without clean holders — not a reason to call")

    if critical:
        verdict = RiskVerdict.FAIL
    elif len(warnings) >= 2:
        verdict = RiskVerdict.PASS_WITH_WARN
    else:
        verdict = RiskVerdict.PASS
    return DeepRiskReport(
        verdict=verdict,
        checks=checks,
        critical=list(dict.fromkeys(critical)),
        warnings=list(dict.fromkeys(warnings)),
        evidence=evidence,
    )
