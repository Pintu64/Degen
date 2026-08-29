from __future__ import annotations
import asyncio
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
import httpx
from app.config import Settings
from app.domain import Chain, TokenSnapshot
from app.market.base import ProviderError

CHAIN_IDS = {Chain.SOLANA: "solana", Chain.ETHEREUM: "ethereum", Chain.BSC: "bsc"}

def dec(value: Any) -> Decimal | None:
    try:
        if value is None: return None
        result = Decimal(str(value)); return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError): return None

class DexScreenerProvider:
    name = "dexscreener"
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None): self.client = client or httpx.AsyncClient(base_url=settings.dexscreener_base_url, timeout=15)
    async def close(self): await self.client.aclose()
    def normalize(self, chain: Chain, pair: dict[str, Any]) -> TokenSnapshot | None:
        base=pair.get("baseToken") or {}; address=base.get("address")
        if not address: return None
        tx=pair.get("txns") or {}; h24=tx.get("h24") or {}; volume=pair.get("volume") or {}; change=pair.get("priceChange") or {}; liq=pair.get("liquidity") or {}
        created=pair.get("pairCreatedAt"); created_dt=datetime.fromtimestamp(created/1000, UTC) if created else None; age=int((datetime.now(UTC)-created_dt).total_seconds()) if created_dt else None
        buys=h24.get("buys"); sells=h24.get("sells")
        return TokenSnapshot(chain=chain, contract_address=str(address), name=base.get("name"), symbol=base.get("symbol"), price=dec(pair.get("priceUsd")), market_cap=dec(pair.get("marketCap")), fdv=dec(pair.get("fdv")), liquidity=dec(liq.get("usd")), volume_1h=dec(volume.get("h1")), volume_6h=dec(volume.get("h6")), volume_24h=dec(volume.get("h24")), price_change_1h=dec(change.get("h1")), price_change_6h=dec(change.get("h6")), price_change_24h=dec(change.get("h24")), buys=buys, sells=sells, transactions=(buys+sells if isinstance(buys,int) and isinstance(sells,int) else None), pair_age_seconds=age, token_age_seconds=age, dex=pair.get("dexId"), pair_address=pair.get("pairAddress"), chart_url=pair.get("url") or None, timestamp=datetime.now(UTC), provider=self.name)
    async def _get(self, path: str) -> Any:
        for attempt in range(3):
            try:
                response=await self.client.get(path); response.raise_for_status(); return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                if attempt == 2: raise ProviderError(str(exc)) from exc
                await asyncio.sleep(2**attempt)
    async def discover_tokens(self, chain: Chain) -> list[TokenSnapshot]:
        data=await self._get("/token-boosts/latest/v1"); addresses=[x.get("tokenAddress") for x in data if x.get("chainId")==CHAIN_IDS[chain]][:30]
        snapshots=await asyncio.gather(*(self.get_snapshot(chain,a) for a in addresses), return_exceptions=True)
        return [s for s in snapshots if isinstance(s,TokenSnapshot)]
    async def get_snapshot(self, chain: Chain, address: str) -> TokenSnapshot | None:
        data=await self._get(f"/latest/dex/tokens/{address}"); pairs=[p for p in data.get("pairs",[]) if p.get("chainId")==CHAIN_IDS[chain]]; snapshots=[self.normalize(chain,p) for p in pairs]; snapshots=[s for s in snapshots if s and s.price and s.liquidity]
        return max(snapshots,key=lambda s:s.liquidity or 0) if snapshots else None
