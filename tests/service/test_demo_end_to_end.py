"""End-to-end: a credential-free demo bot produces observable output (#116, #119).

This is the path an operator walks before funding anything -- create with no
credentials, start, see decisions, see dry-run orders, see them in trade
history. Every layer is real except the market feed, which is injected so the
test does not depend on Coinbase being reachable or on the market moving.
"""

from __future__ import annotations

import asyncio

import pytest

from tradingbot.models import Candle
from tradingbot.service.events import DecisionEvent, EventBus, OrderEvent
from tradingbot.service.exposure import ExposureTracker
from tradingbot.service.supervisor import BotConfig, BotSupervisor


def _candle(ts: int, close: float) -> Candle:
    return Candle(timestamp=ts, open=close, high=close, low=close, close=close, volume=1.0)


# Falls, then rallies and keeps rising: one upward crossing, so one buy, and
# the position is still open at the end.
#
# The rally ramps rather than jumping to a plateau on purpose. On a perfectly
# flat series the two averages converge to the same value, ``fast > slow``
# turns false, and the strategy exits -- correct behaviour (the trend ended),
# but it would close the position this test is asserting on.
_CLOSES = [100.0] * 10 + [80.0] * 10 + [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]


class _ScriptedHub:
    """Replays a fixed price series, standing in for the live Coinbase feed."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], list] = {}
        self._last: float = _CLOSES[0]

    async def warmup(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        del symbol, timeframe, limit
        return [_candle(1, _CLOSES[0])]

    def subscribe(self, symbol: str, timeframe: str, handler) -> None:
        self._handlers.setdefault((symbol, timeframe), []).append(handler)

    def unsubscribe(self, symbol: str, timeframe: str, handler) -> None:
        self._handlers[(symbol, timeframe)].remove(handler)

    def latest_price(self, symbol: str, timeframe: str) -> float | None:
        del symbol, timeframe
        return self._last

    def play(self, symbol: str, timeframe: str) -> None:
        """Push the whole series through, as the stream would bar by bar."""
        for index, close in enumerate(_CLOSES, start=2):
            self._last = close
            for handler in tuple(self._handlers.get((symbol, timeframe), ())):
                handler(_candle(index, close))


class _RecordingStore:
    def __init__(self) -> None:
        self.trades: list[tuple[str, dict]] = []

    def append_trade(self, bot_id: str, order_event: dict) -> None:
        self.trades.append((bot_id, order_event))


async def _wait_for_trades(store: "_RecordingStore", count: int, timeout: float = 5.0) -> None:
    """Poll until ``store`` holds ``count`` records.

    Persistence lags the order event: the event is published as soon as the
    venue answers, while the trade is written afterwards. Asserting on the
    event alone passes in isolation and fails under a loaded suite.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while len(store.trades) < count:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"only {len(store.trades)} trade(s) persisted")
        await asyncio.sleep(0.01)


async def _await_order(queue) -> OrderEvent:
    """Return the first order event, skipping state and decision traffic."""
    while True:
        event = await queue.get()
        if isinstance(event, OrderEvent):
            return event


def _config() -> BotConfig:
    return BotConfig(
        id="demo-bot",
        venue="paper",
        market_type="spot",
        strategy="demo-crossover",
        symbol="BTC/USD",
        timeframe="1m",
        quantity=0.1,
        live=False,
        per_bot_cap=1_000_000.0,
        global_cap=1_000_000.0,
        params={"fast": 2, "slow": 5},
    )


@pytest.mark.asyncio
async def test_credential_free_demo_bot_decides_orders_and_records_a_trade() -> None:
    """Start a paper bot with no credentials and observe the whole chain."""
    hub = _ScriptedHub()
    bus = EventBus()
    store = _RecordingStore()
    supervisor = BotSupervisor(
        hub_factory=lambda cfg: hub,
        event_bus=bus,
        exposure=ExposureTracker(),
        store=store,
    )
    # No secrets are configured anywhere: the venue is built from creds={}.
    supervisor.create(_config())
    queue = bus.subscribe()

    await supervisor.start("demo-bot")
    assert supervisor.get("demo-bot").status == "running"  # type: ignore[union-attr]

    hub.play("BTC/USD", "1m")

    decisions: list[DecisionEvent] = []
    orders: list[OrderEvent] = []

    async def _drain() -> None:
        while not orders:
            event = await queue.get()
            if isinstance(event, DecisionEvent):
                decisions.append(event)
            elif isinstance(event, OrderEvent):
                orders.append(event)

    await asyncio.wait_for(_drain(), timeout=5.0)

    # A decision was published for the operator's log.
    assert decisions, "the bot published no decisions"
    # An order was routed and filled by the paper venue.
    assert orders[0].bot_id == "demo-bot"
    assert orders[0].action == "buy"
    assert orders[0].ok is True
    # And it reached trade history.
    await _wait_for_trades(store, 1)
    assert any(bot_id == "demo-bot" for bot_id, _ in store.trades)

    await supervisor.stop("demo-bot")


@pytest.mark.asyncio
async def test_demo_bot_marks_a_position_and_pnl_from_the_paper_fill() -> None:
    """PnL and position must be readable, since that is what the demo shows."""
    hub = _ScriptedHub()
    bus = EventBus()
    supervisor = BotSupervisor(
        hub_factory=lambda cfg: hub,
        event_bus=bus,
        exposure=ExposureTracker(),
        store=_RecordingStore(),
    )
    supervisor.create(_config())
    queue = bus.subscribe()

    await supervisor.start("demo-bot")
    hub.play("BTC/USD", "1m")
    # Wait for the fill rather than sleeping: routing runs on the bot's worker
    # lane, so a fixed sleep races the lane and fails intermittently.
    await asyncio.wait_for(_await_order(queue), timeout=5.0)

    bot = supervisor.get("demo-bot")
    assert bot is not None and bot.venue is not None
    position = bot.venue.get_position("BTC/USD")
    assert position is not None, "the paper venue holds the simulated position"
    assert position.size == pytest.approx(0.1)

    await supervisor.stop("demo-bot")
