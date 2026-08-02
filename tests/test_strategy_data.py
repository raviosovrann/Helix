"""Tests for the typed strategy market-data contract (#130)."""

from __future__ import annotations

import asyncio

import pytest

from helix.models import Candle
from helix.strategies.base import DataRequirements, MarketData
from helix.service.strategy_data import HubMarketData, MissingHistoryError


def _c(timestamp: int) -> Candle:
    return Candle(
        timestamp=timestamp,
        open=1.0,
        high=1.0,
        low=1.0,
        close=float(timestamp),
        volume=1.0,
    )


class _FakeHub:
    """Stands in for MarketDataHub: async warmup, sync latest_price."""

    def __init__(self, depth: int = 500) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self._depth = depth

    async def warmup(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        self.calls.append((symbol, timeframe, limit))
        return [_c(i) for i in range(1, min(limit, self._depth) + 1)]

    def latest_price(self, symbol: str, timeframe: str) -> float | None:
        del symbol, timeframe
        return 42.0


def test_hub_market_data_satisfies_the_protocol() -> None:
    """The adapter is what strategies are typed against, so it must conform."""
    assert isinstance(HubMarketData(_FakeHub(), symbol="BTC/USD"), MarketData)


def test_a_feed_without_the_contract_is_not_market_data() -> None:
    """Guards the mismatch #130 exists to fix.

    The supervisor used to pass a hub exposing async ``warmup()`` into a field
    documented as a synchronous ``warmup_candles()`` feed. Nothing caught it
    because the field was typed ``Any`` and the only strategy ignored it.
    """

    class _WarmupCandlesFeed:
        def warmup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
            del symbol, timeframe, limit
            return []

    assert not isinstance(_WarmupCandlesFeed(), MarketData)


def test_prefetched_candles_are_readable_synchronously() -> None:
    """Strategy evaluation runs on a worker lane and cannot await."""
    hub = _FakeHub()
    data = HubMarketData(hub, symbol="BTC/USD")

    asyncio.run(data.prefetch(DataRequirements(history={"30m": 200})))

    candles = data.candles("BTC/USD", "30m", 200)
    assert len(candles) == 200
    assert hub.calls == [("BTC/USD", "30m", 200)]


def test_candles_returns_the_newest_when_fewer_are_asked_for() -> None:
    """A strategy sizing itself for 20 bars must not receive 200."""
    data = HubMarketData(_FakeHub(), symbol="BTC/USD")
    asyncio.run(data.prefetch(DataRequirements(history={"30m": 200})))

    recent = data.candles("BTC/USD", "30m", 20)

    assert [candle.timestamp for candle in recent] == list(range(181, 201))


def test_undeclared_timeframe_raises_rather_than_returning_empty() -> None:
    """Silence here would be a strategy evaluating on no history at all.

    An empty list is indistinguishable from a quiet market, so a strategy would
    keep running and quietly stop taking the trades it was written to take.
    """
    data = HubMarketData(_FakeHub(), symbol="BTC/USD")
    asyncio.run(data.prefetch(DataRequirements(history={"30m": 200})))

    with pytest.raises(MissingHistoryError, match="4h"):
        data.candles("BTC/USD", "4h", 50)


def test_prefetch_covers_every_declared_timeframe() -> None:
    """A multi-timeframe strategy needs all of its timeframes ready up front."""
    hub = _FakeHub()
    data = HubMarketData(hub, symbol="BTC/USD")

    asyncio.run(data.prefetch(DataRequirements(history={"30m": 200, "4h": 50})))

    assert sorted(hub.calls) == [("BTC/USD", "30m", 200), ("BTC/USD", "4h", 50)]
    assert len(data.candles("BTC/USD", "4h", 50)) == 50


def test_refresh_replaces_history_without_widening_the_contract() -> None:
    """Higher timeframes go stale; the poll tick refreshes them (#130)."""
    hub = _FakeHub()
    data = HubMarketData(hub, symbol="BTC/USD")
    requirements = DataRequirements(history={"4h": 50})

    asyncio.run(data.prefetch(requirements))
    asyncio.run(data.prefetch(requirements))

    assert len(hub.calls) == 2, "refresh refetches; the hub owns the caching"
    assert len(data.candles("BTC/USD", "4h", 50)) == 50


def test_latest_price_delegates_to_the_hub() -> None:
    """Price comes from the live stream, not the warmup snapshot."""
    data = HubMarketData(_FakeHub(), symbol="BTC/USD")
    assert data.latest_price("BTC/USD", "30m") == 42.0


def test_empty_requirements_prefetch_nothing() -> None:
    """Requirements are opt-in, as in #125: declaring nothing costs nothing."""
    hub = _FakeHub()
    data = HubMarketData(hub, symbol="BTC/USD")

    asyncio.run(data.prefetch(DataRequirements()))

    assert hub.calls == []
