from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from time import monotonic
from typing import Any

import httpx
from pydantic import HttpUrl, ValidationError

from app.config import Settings
from app.domain import Chain, TokenSnapshot
from app.market.base import ProviderError, TokenDiscoveryProvider

CHAIN_IDS = {Chain.SOLANA: "solana", Chain.ETHEREUM: "ethereum", Chain.BSC: "bsc", Chain.BASE: "base"}
_EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_SOLANA_ADDRESS_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DISCOVERY_PATHS = (
    "/token-boosts/latest/v1",
    "/token-boosts/top/v1",
    "/token-profiles/latest/v1",
    "/token-profiles/recent-updates/v1",
    "/ads/latest/v1",
    "/community-takeovers/latest/v1",
)


def dec(value: Any) -> Decimal | None:
    try:
        if value is None:
            return None
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def items_from_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "tokens", "boosts", "profiles", "pairs", "ads"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if "tokenAddress" in data or "chainId" in data or "baseToken" in data:
            return [data]
    return []


def pairs_from_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict) and (item.get("baseToken") or item.get("pairAddress"))]
    if isinstance(data, dict):
        pairs = data.get("pairs")
        if isinstance(pairs, list):
            return [item for item in pairs if isinstance(item, dict)]
        if data.get("baseToken") or data.get("pairAddress"):
            return [data]
    return []


def _http_url(value: Any) -> HttpUrl | None:
    if not value:
        return None
    try:
        return HttpUrl(str(value))
    except (ValidationError, TypeError, ValueError):
        return None


def _rank(snapshot: TokenSnapshot) -> tuple[Decimal, Decimal, int]:
    return (
        snapshot.volume_24h or Decimal("0"),
        snapshot.liquidity or Decimal("0"),
        snapshot.transactions or 0,
    )


def valid_contract_address(chain: Chain, address: Any) -> bool:
    if not isinstance(address, str):
        return False
    pattern = _SOLANA_ADDRESS_RE if not chain.is_evm else _EVM_ADDRESS_RE
    return bool(pattern.fullmatch(address.strip()))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _created_datetime(value: Any) -> datetime | None:
    milliseconds = dec(value)
    if milliseconds is None or milliseconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(float(milliseconds / Decimal("1000")), UTC)
    except (OverflowError, OSError, ValueError):
        return None


class DexScreenerProvider(TokenDiscoveryProvider):
    name = "dexscreener"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(
            base_url=settings.dexscreener_base_url,
            timeout=httpx.Timeout(6.0, connect=2.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=40),
        )
        self._address_cache: tuple[float, dict[str, list[str]]] | None = None
        self._meta_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._fresh_cache: tuple[float, dict[str, list[str]]] | None = None
        self._snap_cache: dict[tuple[str, str], tuple[float, TokenSnapshot]] = {}

    async def close(self) -> None:
        await self.client.aclose()

    def normalize(self, chain: Chain, pair: dict[str, Any]) -> TokenSnapshot | None:
        base = _mapping(pair.get("baseToken"))
        quote = _mapping(pair.get("quoteToken"))
        address = base.get("address")
        if not valid_contract_address(chain, address):
            return None
        tx = _mapping(pair.get("txns"))
        h24 = _mapping(tx.get("h24"))
        m5 = _mapping(tx.get("m5"))
        volume = _mapping(pair.get("volume"))
        change = _mapping(pair.get("priceChange"))
        liq = pair.get("liquidity")
        info = _mapping(pair.get("info"))
        created_dt = _created_datetime(pair.get("pairCreatedAt"))
        age = max(0, int((datetime.now(UTC) - created_dt).total_seconds())) if created_dt else None
        buys = h24.get("buys")
        sells = h24.get("sells")
        buys_m5 = m5.get("buys")
        sells_m5 = m5.get("sells")
        websites = info.get("websites") if isinstance(info.get("websites"), list) else []
        socials = info.get("socials") if isinstance(info.get("socials"), list) else []
        website = _http_url(websites[0].get("url") if websites and isinstance(websites[0], dict) else None)
        social_urls = [url for url in (_http_url(item.get("url")) for item in socials if isinstance(item, dict)) if url]
        try:
            return TokenSnapshot(
                chain=chain,
                contract_address=str(address),
                name=base.get("name"),
                symbol=base.get("symbol"),
                price=dec(pair.get("priceUsd")),
                market_cap=dec(pair.get("marketCap")),
                fdv=dec(pair.get("fdv")),
                liquidity=dec(liq.get("usd")) if isinstance(liq, dict) else dec(liq),
                volume_m5=dec(volume.get("m5")),
                volume_1h=dec(volume.get("h1")),
                volume_6h=dec(volume.get("h6")),
                volume_24h=dec(volume.get("h24")),
                price_change_m5=dec(change.get("m5")),
                price_change_1h=dec(change.get("h1")),
                price_change_6h=dec(change.get("h6")),
                price_change_24h=dec(change.get("h24")),
                buys=buys if isinstance(buys, int) else None,
                sells=sells if isinstance(sells, int) else None,
                buys_m5=buys_m5 if isinstance(buys_m5, int) else None,
                sells_m5=sells_m5 if isinstance(sells_m5, int) else None,
                transactions=(buys + sells) if isinstance(buys, int) and isinstance(sells, int) else None,
                boosted=bool(pair.get("boosts") or pair.get("paid") or pair.get("hasBoost")),
                pair_age_seconds=age,
                token_age_seconds=age,
                dex=pair.get("dexId"),
                pair_address=pair.get("pairAddress"),
                quote_symbol=quote.get("symbol"),
                chart_url=_http_url(pair.get("url")),
                website_url=website,
                social_urls=social_urls,
                timestamp=datetime.now(UTC),
                provider=self.name,
            )
        except ValidationError:
            return None

    async def _get(self, path: str) -> Any:
        for attempt in range(2):
            try:
                response = await self.client.get(path)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status < 500 and status != 429:
                    raise ProviderError(f"DexScreener returned HTTP {status}") from exc
                if attempt == 1:
                    raise ProviderError(str(exc)) from exc
                retry_after = dec(exc.response.headers.get("Retry-After"))
                delay = float(retry_after) if retry_after is not None and 0 < retry_after <= 8 else 0.4
                await asyncio.sleep(delay)
            except (httpx.HTTPError, ValueError) as exc:
                if attempt == 1:
                    raise ProviderError(str(exc)) from exc
                await asyncio.sleep(0.3)

    async def _get_optional(self, path: str) -> Any:
        try:
            return await self._get(path)
        except ProviderError:
            return None

    def _best_snapshot(self, chain: Chain, pairs: list[dict[str, Any]]) -> TokenSnapshot | None:
        snapshots = []
        for pair in pairs:
            pair_chain = pair.get("chainId")
            if pair_chain is not None and str(pair_chain).lower() != CHAIN_IDS[chain]:
                continue
            snapshot = self.normalize(chain, pair)
            if snapshot and snapshot.price and snapshot.price > 0:
                snapshots.append(snapshot)
        if not snapshots:
            return None
        return max(snapshots, key=_rank)

    def _merge(self, snapshots: list[TokenSnapshot]) -> list[TokenSnapshot]:
        best: dict[str, TokenSnapshot] = {}
        for snapshot in snapshots:
            key = snapshot.contract_address
            current = best.get(key)
            if current is None or _rank(snapshot) > _rank(current):
                best[key] = snapshot
        return list(best.values())

    async def get_snapshots(self, chain: Chain, addresses: list[str]) -> list[TokenSnapshot]:
        unique: list[str] = []
        seen: set[str] = set()
        for address in addresses:
            if not valid_contract_address(chain, address):
                continue
            address = address.strip()
            key = address.lower() if chain.is_evm else address
            if key in seen:
                continue
            seen.add(key)
            unique.append(address)
        async def fetch_chunk(chunk: list[str]) -> list[TokenSnapshot]:
            data = await self._get_optional(f"/tokens/v1/{CHAIN_IDS[chain]}/{','.join(chunk)}")
            pairs = pairs_from_payload(data)
            if not pairs:
                data = await self._get_optional(f"/latest/dex/tokens/{','.join(chunk)}")
                pairs = pairs_from_payload(data)
            grouped: dict[str, list[dict[str, Any]]] = {}
            requested = {item.lower() if chain.is_evm else item for item in chunk}
            found: list[TokenSnapshot] = []
            for pair in pairs:
                base = _mapping(pair.get("baseToken")).get("address")
                if not base:
                    continue
                key = str(base).lower() if chain.is_evm else str(base)
                if key not in requested:
                    continue
                grouped.setdefault(key, []).append(pair)
            for group in grouped.values():
                snapshot = self._best_snapshot(chain, group)
                if snapshot:
                    found.append(snapshot)
            return found

        chunks = [unique[index:index + 30] for index in range(0, len(unique), 30)]
        parts = await asyncio.gather(*(fetch_chunk(chunk) for chunk in chunks), return_exceptions=True)
        snapshots: list[TokenSnapshot] = []
        for part in parts:
            if isinstance(part, list):
                snapshots.extend(part)
        return snapshots

    async def get_snapshot(self, chain: Chain, address: str) -> TokenSnapshot | None:
        key = (chain.value, address.lower() if chain.is_evm else address)
        hit = self._snap_cache.get(key)
        if hit and monotonic() - hit[0] < 8:
            return hit[1]
        snapshots = await self.get_snapshots(chain, [address])
        if snapshots:
            self._snap_cache[key] = (monotonic(), snapshots[0])
            if len(self._snap_cache) > 120:
                oldest = sorted(self._snap_cache, key=lambda item: self._snap_cache[item][0])[:40]
                for item in oldest:
                    self._snap_cache.pop(item, None)
            return snapshots[0]
        return None

    async def _discovery_addresses(self) -> dict[str, list[str]]:
        now = monotonic()
        if self._address_cache and now - self._address_cache[0] < 12:
            return self._address_cache[1]
        buckets: dict[str, list[str]] = {chain.value: [] for chain in Chain}
        seen: dict[str, set[str]] = {chain.value: set() for chain in Chain}
        results = await asyncio.gather(*(self._get_optional(path) for path in DISCOVERY_PATHS), return_exceptions=True)
        for data in results:
            for item in items_from_payload(data):
                chain_id = str(item.get("chainId") or "").lower()
                address = item.get("tokenAddress")
                if chain_id not in seen or not valid_contract_address(Chain(chain_id), address):
                    continue
                normalized = str(address).lower() if chain_id in {Chain.ETHEREUM.value, Chain.BSC.value, Chain.BASE.value} else str(address)
                if normalized in seen[chain_id]:
                    continue
                seen[chain_id].add(normalized)
                buckets[chain_id].append(str(address))
        self._address_cache = (now, buckets)
        return buckets

    async def _meta_pairs(self) -> list[dict[str, Any]]:
        now = monotonic()
        if self._meta_cache and now - self._meta_cache[0] < 12:
            return self._meta_cache[1]
        trending = items_from_payload(await self._get_optional("/metas/trending/v1"))
        slugs = [item.get("slug") for item in trending[:4] if item.get("slug")]
        results = await asyncio.gather(
            *(self._get_optional(f"/metas/meta/v1/{slug}") for slug in slugs),
            return_exceptions=True,
        )
        pairs: list[dict[str, Any]] = []
        for data in results:
            if isinstance(data, dict):
                pairs.extend(pairs_from_payload(data.get("pairs") or data))
        self._meta_cache = (now, pairs)
        return pairs

    async def _fresh_addresses(self, chains: list[Chain] | None = None) -> dict[str, list[str]]:
        wanted = chains or list(Chain)
        now = monotonic()
        if self._fresh_cache and now - self._fresh_cache[0] < 20:
            cached = self._fresh_cache[1]
            return {chain.value: list(cached.get(chain.value, [])) for chain in wanted}
        networks = {
            Chain.SOLANA: "solana",
            Chain.ETHEREUM: "eth",
            Chain.BSC: "bsc",
            Chain.BASE: "base",
        }
        buckets: dict[str, list[str]] = {chain.value: [] for chain in Chain}
        jobs = []
        for chain in wanted:
            network = networks.get(chain)
            if not network:
                continue
            jobs.append((chain, f"https://api.geckoterminal.com/api/v2/networks/{network}/new_pools"))
            jobs.append((chain, f"https://api.geckoterminal.com/api/v2/networks/{network}/trending_pools"))
        results = await asyncio.gather(*(self._get_optional(url) for _, url in jobs), return_exceptions=True)
        seen: dict[str, set[str]] = {chain.value: set() for chain in Chain}
        for (chain, _), data in zip(jobs, results):
            if not isinstance(data, dict):
                continue
            rows = data.get("data") if isinstance(data.get("data"), list) else []
            for item in rows:
                if not isinstance(item, dict):
                    continue
                rel = ((item.get("relationships") or {}).get("base_token") or {}).get("data") or {}
                ident = str(rel.get("id") or "")
                address = ident.split("_", 1)[1] if "_" in ident else ""
                if not address or not valid_contract_address(chain, address):
                    continue
                key = address.lower() if chain.is_evm else address
                if key in seen[chain.value]:
                    continue
                seen[chain.value].add(key)
                buckets[chain.value].append(address)
        self._fresh_cache = (now, buckets)
        return buckets

    async def discover_tokens(self, chain: Chain) -> list[TokenSnapshot]:
        found = await self.discover_many([chain])
        return found.get(chain, [])

    async def discover_many(self, chains: list[Chain]) -> dict[Chain, list[TokenSnapshot]]:
        if not chains:
            return {}
        addresses_task = asyncio.create_task(self._discovery_addresses())
        meta_task = asyncio.create_task(self._meta_pairs())
        fresh_task = asyncio.create_task(self._fresh_addresses(chains))
        buckets = await addresses_task
        fresh = await fresh_task

        async def load(chain: Chain) -> tuple[Chain, list[TokenSnapshot]]:
            merged: list[str] = []
            seen: set[str] = set()
            for address in (fresh.get(chain.value, []) + buckets.get(chain.value, [])):
                key = address.lower() if chain.is_evm else address
                if key in seen:
                    continue
                seen.add(key)
                merged.append(address)
            addresses = merged[:30]
            fetched = await self.get_snapshots(chain, addresses) if addresses else []
            meta_snapshots = []
            for pair in await meta_task:
                if pair.get("chainId") != CHAIN_IDS[chain]:
                    continue
                snapshot = self.normalize(chain, pair)
                if snapshot and snapshot.price and snapshot.price > 0:
                    meta_snapshots.append(snapshot)
            return chain, self._merge(fetched + meta_snapshots)

        loaded = await asyncio.gather(*(load(chain) for chain in chains), return_exceptions=True)
        result: dict[Chain, list[TokenSnapshot]] = {}
        for item in loaded:
            if isinstance(item, tuple):
                result[item[0]] = item[1]
        return result
