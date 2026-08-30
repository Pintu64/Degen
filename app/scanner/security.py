from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from time import monotonic

import httpx

from app.config import get_settings
from app.domain import Chain, CoinScan, TokenSnapshot

logger = logging.getLogger(__name__)

GOPLUS_CHAIN = {Chain.ETHEREUM: "1", Chain.BSC: "56", Chain.BASE: "8453"}
FATAL_KEYS = {"honeypot", "rugged", "blacklist", "mint+freeze", "high tax"}
_SCAN_CACHE: dict[str, tuple[float, CoinScan]] = {}
_BIRDEYE_COOLDOWN_UNTIL = 0.0
_SCAN_TTL = 45.0
_BIRDEYE_COOLDOWN = 45.0


def _dec(value) -> Decimal | None:
    try:
        if value is None or value == "":
            return None
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except Exception:
        return None


def _tax_pct(value) -> Decimal | None:
    number = _dec(value)
    if number is None:
        return None
    if number <= 1:
        return number * Decimal("100")
    return number


def _boolish(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "open", "enabled"}:
        return True
    if text in {"0", "false", "no", "null", "none", "revoked", "disabled"}:
        return False
    return None


def _authority_open(value) -> bool | None:
    if value is None or value == "" or value is False:
        return False
    if value is True:
        return True
    text = str(value).strip().lower()
    if text in {"null", "none", "", "0", "false"}:
        return False
    return True


def _mark(ok: bool | None, good: str, bad: str, unknown: str = "❔ UNKNOWN") -> str:
    if ok is True:
        return f"✅ {good}"
    if ok is False:
        return f"🛑 {bad}"
    return unknown


def _apply_to_snapshot(snapshot: TokenSnapshot, scan: CoinScan) -> None:
    if scan.mint_authority is not None:
        snapshot.mint_authority = scan.mint_authority
    if scan.freeze_authority is not None:
        snapshot.freeze_authority = scan.freeze_authority
    if scan.ownership_renounced is not None:
        snapshot.ownership_renounced = scan.ownership_renounced
    if scan.verified is not None:
        snapshot.contract_verified = scan.verified
    if scan.buy_tax is not None:
        snapshot.buy_tax = scan.buy_tax
    if scan.sell_tax is not None:
        snapshot.sell_tax = scan.sell_tax
    if scan.holders is not None:
        snapshot.holders = scan.holders
    if scan.top10_percent is not None:
        snapshot.top_holder_percentage = scan.top10_percent
    if scan.flags:
        snapshot.suspicious_flags = list(dict.fromkeys([*snapshot.suspicious_flags, *scan.flags]))


def finalize(scan: CoinScan) -> CoinScan:
    flags = list(scan.flags)
    if scan.honeypot:
        flags.append("Honeypot")
        scan.fatal = True
    if scan.rugged:
        flags.append("Marked rugged")
        scan.fatal = True
    if scan.blacklist:
        flags.append("Blacklist function")
        scan.fatal = True
    if scan.mint_authority and scan.freeze_authority:
        flags.append("Mint + freeze still open")
        scan.fatal = True
    if scan.top10_percent is not None and scan.top10_percent > 45:
        flags.append("Top10 over 45%")
        scan.fatal = True
    buy = scan.buy_tax or Decimal("0")
    sell = scan.sell_tax or Decimal("0")
    if (scan.buy_tax is not None and buy > 8) or (scan.sell_tax is not None and sell > 8):
        flags.append("High tax")
        scan.fatal = True
    scan.flags = list(dict.fromkeys(flags))
    scan.checks = {
        "honeypot": _mark(False if scan.honeypot else (True if scan.honeypot is False else None), "CLEAN", "HONEYPOT"),
        "mint": _mark(False if scan.mint_authority else (True if scan.mint_authority is False else None), "REVOKED", "MINT OPEN"),
        "freeze": _mark(False if scan.freeze_authority else (True if scan.freeze_authority is False else None), "REVOKED", "FREEZE OPEN"),
        "owner": _mark(scan.ownership_renounced, "RENOUNCED", "DEV CAN RUG"),
        "lp": _mark(scan.lp_locked, "LOCKED/BURNED", "UNLOCKED LP"),
        "verified": _mark(scan.verified, "VERIFIED", "UNVERIFIED"),
        "blacklist": _mark(False if scan.blacklist else (True if scan.blacklist is False else None), "NONE", "BLACKLIST"),
        "proxy": _mark(False if scan.proxy else (True if scan.proxy is False else None), "NO PROXY", "PROXY"),
    }
    score = 70
    if scan.honeypot:
        score -= 50
    if scan.rugged:
        score -= 50
    if scan.blacklist:
        score -= 25
    if scan.mint_authority:
        score -= 15
    if scan.freeze_authority:
        score -= 15
    if scan.lp_locked is True:
        score += 10
    elif scan.lp_locked is False:
        score -= 10
    if scan.ownership_renounced:
        score += 6
    if scan.top10_percent is not None:
        if scan.top10_percent <= 25:
            score += 8
        elif scan.top10_percent > 45:
            score -= 12
    if scan.buy_tax:
        score -= min(20, int(scan.buy_tax))
    if scan.sell_tax:
        score -= min(20, int(scan.sell_tax))
    scan.safety_score = max(0, min(100, score))
    return scan


def _merge_scans(*scans: CoinScan) -> CoinScan:
    keep = [item for item in scans if item and item.source not in {"none", "error", ""}]
    if not keep:
        return CoinScan(source="none")
    out = CoinScan(source="+".join(dict.fromkeys(item.source for item in keep)))
    prefer = ("fluxrpc", "shield", "birdeye", "rugcheck", "rugcheck-summary", "goplus")
    ordered = sorted(keep, key=lambda item: prefer.index(item.source) if item.source in prefer else 99)
    birdeye_holders = None
    for item in reversed(ordered):
        for field in ("honeypot", "mint_authority", "freeze_authority", "ownership_renounced", "buy_tax", "sell_tax", "top10_percent", "lp_locked", "lp_locked_percent", "verified", "proxy", "blacklist", "rugged"):
            value = getattr(item, field)
            if value is not None:
                setattr(out, field, value)
        if item.holders is not None:
            if "birdeye" in item.source:
                birdeye_holders = item.holders
            elif out.holders is None:
                out.holders = item.holders
        if item.top_holders and not out.top_holders:
            out.top_holders = list(item.top_holders)
        out.flags.extend(item.flags)
    if birdeye_holders is not None:
        out.holders = birdeye_holders
    out.flags = list(dict.fromkeys(out.flags))
    return out


def parse_spl_mint(payload: dict) -> CoinScan:
    value = (payload.get("result") or {}).get("value") if isinstance(payload.get("result"), dict) else payload.get("value")
    info = (((value or {}).get("data") or {}).get("parsed") or {}).get("info") if isinstance(value, dict) else None
    if not isinstance(info, dict):
        return CoinScan(source="error")
    return CoinScan(
        mint_authority=_authority_open(info.get("mintAuthority")),
        freeze_authority=_authority_open(info.get("freezeAuthority")),
        source="fluxrpc",
    )


def top10_from_largest(mint_payload: dict, largest_payload: dict) -> Decimal | None:
    value = (mint_payload.get("result") or {}).get("value") if isinstance(mint_payload.get("result"), dict) else None
    info = (((value or {}).get("data") or {}).get("parsed") or {}).get("info") if isinstance(value, dict) else None
    supply = _dec((info or {}).get("supply")) if isinstance(info, dict) else None
    accounts = (largest_payload.get("result") or {}).get("value") if isinstance(largest_payload.get("result"), dict) else None
    if supply is None or supply <= 0 or not isinstance(accounts, list):
        return None
    total = Decimal("0")
    for item in accounts[:10]:
        amount = _dec(item.get("amount") if isinstance(item, dict) else None)
        if amount is not None:
            total += amount
    return (total / supply) * Decimal("100")


async def _rpc_solana(http: httpx.AsyncClient, mint: str) -> CoinScan:
    settings = get_settings()
    urls = [item for item in (settings.fluxrpc_url, settings.flux_shield_url) if item]
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo", "params": [mint, {"encoding": "jsonParsed"}]},
        {"jsonrpc": "2.0", "id": 2, "method": "getTokenLargestAccounts", "params": [mint]},
    ]
    last = CoinScan(source="error")
    headers = {"X-API-KEY": settings.fluxrpc_api_key} if settings.fluxrpc_api_key else None
    for url in urls:
        try:
            response = await http.post(url, json=batch, headers=headers)
            if response.status_code != 200:
                continue
            payload = response.json()
            rows = payload if isinstance(payload, list) else [payload]
            mint_row = next((item for item in rows if isinstance(item, dict) and item.get("id") == 1), None)
            large_row = next((item for item in rows if isinstance(item, dict) and item.get("id") == 2), None)
            if not isinstance(mint_row, dict):
                continue
            scan = parse_spl_mint(mint_row)
            if isinstance(large_row, dict):
                top10 = top10_from_largest(mint_row, large_row)
                accounts = (large_row.get("result") or {}).get("value") if isinstance(large_row.get("result"), dict) else None
                if isinstance(accounts, list) and accounts:
                    scan.top10_percent = top10
                    supply = None
                    mint_value = (mint_row.get("result") or {}).get("value") if isinstance(mint_row.get("result"), dict) else None
                    info = (((mint_value or {}).get("data") or {}).get("parsed") or {}).get("info") if isinstance(mint_value, dict) else None
                    supply = _dec((info or {}).get("supply")) if isinstance(info, dict) else None
                    rows = []
                    for entry in accounts[:8]:
                        if not isinstance(entry, dict):
                            continue
                        amount = _dec(entry.get("amount"))
                        pct = float((amount / supply) * Decimal("100")) if amount is not None and supply else None
                        rows.append({
                            "address": str(entry.get("address") or "")[:44],
                            "amount": str(entry.get("uiAmountString") or entry.get("amount") or ""),
                            "pct": pct,
                        })
                    scan.top_holders = rows
            if scan.source != "error":
                return scan
            last = scan
        except Exception:
            logger.exception("FLUXRPC_MINT_FAILED")
    return last


async def _birdeye(http: httpx.AsyncClient, snapshot: TokenSnapshot) -> CoinScan:
    global _BIRDEYE_COOLDOWN_UNTIL
    settings = get_settings()
    if not settings.birdeye_api_key:
        return CoinScan(source="none")
    if monotonic() < _BIRDEYE_COOLDOWN_UNTIL:
        return CoinScan(source="none")
    headers = {"X-API-KEY": settings.birdeye_api_key, "x-chain": snapshot.chain.value, "accept": "application/json"}
    try:
        response = await http.get(
            f"{settings.birdeye_base_url.rstrip('/')}/defi/v3/token/market-data",
            params={"address": snapshot.contract_address},
            headers=headers,
        )
        if response.status_code == 429:
            _BIRDEYE_COOLDOWN_UNTIL = monotonic() + _BIRDEYE_COOLDOWN
            return CoinScan(source="error")
        if response.status_code != 200:
            return CoinScan(source="error")
        payload = response.json() if response.content else {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return CoinScan(source="error")
        holders = data.get("holder")
        count = int(holders) if isinstance(holders, (int, float)) and holders >= 0 else None
        return CoinScan(holders=count, source="birdeye")
    except Exception:
        logger.exception("BIRDEYE_MARKET_FAILED")
        return CoinScan(source="error")


def _cached_scan(snapshot: TokenSnapshot) -> CoinScan | None:
    hit = _SCAN_CACHE.get(f"{snapshot.chain.value}:{snapshot.contract_address}")
    if not hit:
        return None
    stamped, scan = hit
    if monotonic() - stamped > _SCAN_TTL:
        return None
    return scan.model_copy(deep=True)


def _store_scan(snapshot: TokenSnapshot, scan: CoinScan) -> None:
    _SCAN_CACHE[f"{snapshot.chain.value}:{snapshot.contract_address}"] = (monotonic(), scan.model_copy(deep=True))
    if len(_SCAN_CACHE) > 80:
        oldest = sorted(_SCAN_CACHE, key=lambda key: _SCAN_CACHE[key][0])[:20]
        for key in oldest:
            _SCAN_CACHE.pop(key, None)


async def scan_coin(snapshot: TokenSnapshot, client: httpx.AsyncClient | None = None) -> CoinScan:
    cached = _cached_scan(snapshot)
    if cached is not None:
        _apply_to_snapshot(snapshot, cached)
        return cached
    own = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(2.4, connect=0.8))
    try:
        if snapshot.chain == Chain.SOLANA:
            parts = await asyncio.gather(
                _rpc_solana(http, snapshot.contract_address),
                _rugcheck_full(http, snapshot.contract_address),
                _goplus_solana(http, snapshot.contract_address),
                return_exceptions=True,
            )
            scans = [item for item in parts if isinstance(item, CoinScan)]
            scan = _merge_scans(*scans) if scans else CoinScan(source="error")
            extra = await _birdeye(http, snapshot)
            if extra.source not in {"none", "error", ""}:
                scan = _merge_scans(scan, extra)
                if extra.holders is not None:
                    scan.holders = extra.holders
        elif snapshot.chain in GOPLUS_CHAIN:
            parts = await asyncio.gather(
                _goplus_full(http, snapshot.chain, snapshot.contract_address),
                _birdeye(http, snapshot),
                return_exceptions=True,
            )
            scans = [item for item in parts if isinstance(item, CoinScan)]
            scan = _merge_scans(*scans) if scans else CoinScan(source="error")
        else:
            scan = CoinScan(source="none")
    except Exception:
        logger.exception("COIN_SCAN_FAILED", extra={"chain": snapshot.chain.value})
        scan = CoinScan(source="error")
    finally:
        if own:
            await http.aclose()
    scan = finalize(scan)
    _apply_to_snapshot(snapshot, scan)
    _store_scan(snapshot, scan)
    return scan


async def inspect(snapshot: TokenSnapshot, client: httpx.AsyncClient | None = None) -> list[str]:
    report = await scan_coin(snapshot, client)
    return report.flags if report.fatal else []


async def _rugcheck_full(http: httpx.AsyncClient, mint: str) -> CoinScan:
    response = await http.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    if response.status_code != 200:
        summary = await http.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary")
        data = summary.json() if summary.status_code == 200 and summary.content else {}
        return _from_rugcheck(data if isinstance(data, dict) else {}, source="rugcheck-summary")
    data = response.json() if response.content else {}
    return _from_rugcheck(data if isinstance(data, dict) else {}, source="rugcheck")


def _from_rugcheck(data: dict, source: str) -> CoinScan:
    token = data.get("token") if isinstance(data.get("token"), dict) else {}
    top = data.get("topHolders") if isinstance(data.get("topHolders"), list) else []
    top10 = Decimal("0")
    holder_rows: list[dict] = []
    for item in top[:10]:
        if not isinstance(item, dict):
            continue
        pct = _dec(item.get("pct") or item.get("percentage") or item.get("percent"))
        if pct is not None:
            if pct > 100:
                pct = pct / Decimal("1000")
            top10 += pct
        addr = str(item.get("owner") or item.get("address") or item.get("wallet") or "")
        holder_rows.append({
            "address": addr[:44],
            "amount": str(item.get("uiAmount") or item.get("amount") or ""),
            "pct": float(pct) if pct is not None else None,
        })
    holders = None
    for key in ("totalHolders", "total_holders", "holderCount"):
        raw = data.get(key)
        if isinstance(raw, (int, float)) and raw > 0:
            holders = int(raw)
            break
    if holders is None:
        nested = _dec(token.get("holders") or token.get("holder"))
        if nested is not None and nested > 0:
            holders = int(nested)
    lp_locked = None
    lp_pct = None
    markets = data.get("markets") if isinstance(data.get("markets"), list) else []
    for market in markets:
        lp = market.get("lp") if isinstance(market, dict) and isinstance(market.get("lp"), dict) else {}
        if not lp:
            continue
        locked = _boolish(lp.get("lpLocked") if "lpLocked" in lp else lp.get("locked"))
        pct = _dec(lp.get("lpLockedPct") or lp.get("lockedPct"))
        if locked or (pct is not None and pct >= 90):
            lp_locked = True
            lp_pct = pct
            break
        if locked is False:
            lp_locked = False
    flags: list[str] = []
    honey = None
    risks = data.get("risks") if isinstance(data.get("risks"), list) else []
    for item in risks:
        name = str(item.get("name") if isinstance(item, dict) else item)
        level = str(item.get("level") if isinstance(item, dict) else "").lower()
        lowered = name.lower()
        if "honeypot" in lowered or "can't sell" in lowered or "cannot sell" in lowered:
            honey = True
            flags.append(name)
        elif name and level in {"danger", "critical", "warn", "warning"}:
            flags.append(name)
    rugged = bool(data.get("rugged"))
    if honey is None and source == "rugcheck" and not rugged:
        honey = False
    return CoinScan(
        honeypot=honey,
        mint_authority=_authority_open(token.get("mintAuthority")),
        freeze_authority=_authority_open(token.get("freezeAuthority")),
        holders=holders,
        top10_percent=top10 if top else None,
        top_holders=holder_rows[:8],
        lp_locked=lp_locked,
        lp_locked_percent=lp_pct,
        rugged=rugged if rugged else None,
        source=source,
        flags=flags,
        safety_score=int(data["score"]) if isinstance(data.get("score"), (int, float)) else None,
    )


def _goplus_status(value) -> bool | None:
    if isinstance(value, dict):
        return _boolish(value.get("status") if "status" in value else value.get("value"))
    return _boolish(value)


async def _goplus_solana(http: httpx.AsyncClient, mint: str) -> CoinScan:
    try:
        response = await http.get(
            "https://api.gopluslabs.io/api/v1/solana/token_security",
            params={"contract_addresses": mint},
        )
    except Exception:
        logger.exception("GOPLUS_SOLANA_FAILED")
        return CoinScan(source="error")
    if response.status_code != 200:
        return CoinScan(source="error")
    payload = response.json() if response.content else {}
    result = payload.get("result") if isinstance(payload, dict) else None
    token = None
    if isinstance(result, dict):
        token = result.get(mint) or result.get(mint.lower()) or next((item for item in result.values() if isinstance(item, dict)), None)
    if not isinstance(token, dict):
        return CoinScan(source="error")
    honey = _goplus_status(token.get("honeypot") or token.get("is_honeypot") or token.get("non_transferable"))
    return CoinScan(
        honeypot=honey,
        mint_authority=_goplus_status(token.get("mintable")),
        freeze_authority=_goplus_status(token.get("freezable") or token.get("freezeable")),
        source="goplus",
        flags=["Non-transferable"] if _goplus_status(token.get("non_transferable")) else [],
    )


async def _goplus_full(http: httpx.AsyncClient, chain: Chain, address: str) -> CoinScan:
    chain_id = GOPLUS_CHAIN[chain]
    response = await http.get(
        f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}",
        params={"contract_addresses": address},
    )
    if response.status_code != 200:
        return CoinScan(source="goplus-error")
    payload = response.json() if response.content else {}
    result = payload.get("result") if isinstance(payload, dict) else None
    token = result.get(address.lower()) if isinstance(result, dict) else None
    if not isinstance(token, dict):
        return CoinScan(source="goplus-empty")
    holders_raw = token.get("holders") if isinstance(token.get("holders"), list) else []
    top10 = Decimal("0")
    for item in holders_raw[:10]:
        if isinstance(item, dict):
            pct = _dec(item.get("percent") or item.get("percentage"))
            if pct is not None:
                top10 += pct * Decimal("100") if pct <= 1 else pct
    lp_holders = token.get("lp_holders") if isinstance(token.get("lp_holders"), list) else []
    locked_pct = Decimal("0")
    saw_lp = False
    for item in lp_holders:
        if not isinstance(item, dict):
            continue
        saw_lp = True
        if _boolish(item.get("is_locked")):
            pct = _dec(item.get("percent"))
            if pct is not None:
                locked_pct += pct * Decimal("100") if pct <= 1 else pct
    holder_count = None
    raw_count = token.get("holder_count")
    if str(raw_count).isdigit():
        holder_count = int(raw_count)
    mintable = _boolish(token.get("is_mintable"))
    owner_renounced = None
    owner = token.get("owner_address")
    if isinstance(owner, str) and owner.lower() in {"", "0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"}:
        owner_renounced = True
    elif owner:
        owner_renounced = False
    if _boolish(token.get("can_take_back_ownership")):
        owner_renounced = False
    return CoinScan(
        honeypot=_boolish(token.get("is_honeypot")),
        mint_authority=mintable,
        freeze_authority=None,
        ownership_renounced=owner_renounced,
        buy_tax=_tax_pct(token.get("buy_tax")),
        sell_tax=_tax_pct(token.get("sell_tax")),
        holders=holder_count,
        top10_percent=top10 if holders_raw else None,
        lp_locked=(locked_pct >= 80) if saw_lp else None,
        lp_locked_percent=locked_pct if saw_lp else None,
        verified=_boolish(token.get("is_open_source")),
        proxy=_boolish(token.get("is_proxy")),
        blacklist=_boolish(token.get("is_blacklisted")),
        source="goplus",
    )
