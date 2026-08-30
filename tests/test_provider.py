from decimal import Decimal

import httpx
import pytest

from app.config import Settings
from app.domain import Chain
from app.market.dexscreener import DexScreenerProvider, dec, valid_contract_address

ETH_ADDRESS = "0x" + "a" * 40
OTHER_ADDRESS = "0x" + "b" * 40
SOL_ADDRESS = "So11111111111111111111111111111111111111112"


def pair(address=ETH_ADDRESS, **overrides):
    value = {
        "chainId": "ethereum",
        "baseToken": {"address": address, "name": "Token", "symbol": "TOK"},
        "priceUsd": "0.000000000001",
        "volume": {"h24": "100"},
        "liquidity": {"usd": "50"},
        "txns": {"h24": {"buys": 4, "sells": 3}},
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("value", [None, "bad", "NaN", "Infinity", object()])
def test_decimal_parser_rejects_invalid_values(value):
    assert dec(value) is None


def test_contract_validation_is_chain_specific():
    assert valid_contract_address(Chain.ETHEREUM, ETH_ADDRESS)
    assert valid_contract_address(Chain.BSC, ETH_ADDRESS)
    assert valid_contract_address(Chain.SOLANA, SOL_ADDRESS)
    assert not valid_contract_address(Chain.ETHEREUM, SOL_ADDRESS)
    assert not valid_contract_address(Chain.SOLANA, "normal message")


def test_normalize_tolerates_malformed_optional_fields():
    provider = DexScreenerProvider(Settings(_env_file=None))
    snapshot = provider.normalize(Chain.ETHEREUM, pair(
        txns="bad",
        volume="bad",
        priceChange=[],
        liquidity="bad",
        info="bad",
        pairCreatedAt="not-a-timestamp",
    ))
    assert snapshot is not None
    assert snapshot.price == Decimal("0.000000000001")
    assert snapshot.transactions is None
    assert snapshot.pair_age_seconds is None


def test_best_snapshot_filters_chain_and_ranks_market_activity():
    provider = DexScreenerProvider(Settings(_env_file=None))
    wrong_chain = pair(chainId="bsc", volume={"h24": "999999"})
    low = pair(volume={"h24": "10"}, liquidity={"usd": "100"})
    high = pair(volume={"h24": "20"}, liquidity={"usd": "50"})
    snapshot = provider._best_snapshot(Chain.ETHEREUM, [wrong_chain, low, high])
    assert snapshot is not None
    assert snapshot.volume_24h == Decimal("20")


@pytest.mark.asyncio
async def test_bulk_lookup_deduplicates_filters_and_falls_back():
    paths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.startswith("/tokens/v1/"):
            return httpx.Response(200, json={"pairs": "malformed"})
        return httpx.Response(200, json={"pairs": [
            pair(),
            pair(chainId="bsc", volume={"h24": "999"}),
            pair(OTHER_ADDRESS),
        ]})

    client = httpx.AsyncClient(base_url="https://api.dexscreener.test", transport=httpx.MockTransport(handler))
    provider = DexScreenerProvider(Settings(_env_file=None), client)
    try:
        snapshots = await provider.get_snapshots(Chain.ETHEREUM, [ETH_ADDRESS, ETH_ADDRESS, "bad"])
    finally:
        await provider.close()

    assert len(snapshots) == 1
    assert snapshots[0].contract_address == ETH_ADDRESS
    assert paths == [
        f"/tokens/v1/ethereum/{ETH_ADDRESS}",
        f"/latest/dex/tokens/{ETH_ADDRESS}",
    ]
