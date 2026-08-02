"""Tests for the market data hub."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from tradingbot.models import Candle
from tradingbot.service.datahub import MarketDataHub
from tradingbot.service.ratelimit import RateLimiter


def _c(timestamp: int) -> Candle:
    return Candle(
        timestamp=timestamp,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=1.0,
    )


class _FakeCandleFeed:
    def __init__(self) -> None:
        self.calls = 0

    def warmup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        del symbol, timeframe, limit
        self.calls += 1
        return [_c(1)]

    def latest_closed_candle(self, symbol: str, timeframe: str) -> Candle:
        del symbol, timeframe
        return _c(1)


class _FakeStream:
    def __init__(self) -> None:
        self.run_calls: list[tuple[str, ...]] = []
        self.stop_calls = 0
        self._handler: Callable[[Candle], None] | None = None
        self._handlers: dict[str, Callable[[Candle], None]] = {}
        self._stopped = asyncio.Event()

    def warmup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        del symbol, timeframe, limit
        return []

    def run(self, *symbols: str) -> None:
        del symbols

    def on_bar(self, handler: Callable[[Candle], None]) -> None:
        self._handler = handler

    def on_bar_for(self, symbol: str, handler: Callable[[Candle], None]) -> None:
        self._handlers[symbol] = handler

    async def run_async(self, *symbols: str) -> None:
        self.run_calls.append(symbols)
        await self._stopped.wait()

    def stop(self) -> None:
        self.stop_calls += 1
        self._stopped.set()

    def emit(self, symbol: str, candle: Candle) -> None:
        handler = self._handlers.get(symbol, self._handler)
        assert handler is not None
        handler(candle)


@pytest.mark.asyncio
async def test_warmup_deduped_and_cached() -> None:
    """Verify that warmup requests are deduplicated and cached."""
    feed = _FakeCandleFeed()
    hub = MarketDataHub(
        stream_feed=_FakeStream(),
        candle_feed=feed,
        limiter=RateLimiter(1000, 1000),
        mtf_cache_seconds=60.0,
        clock=lambda: 0.0,
    )

    first = await hub.warmup("BTC/USD", "1h", 10)
    second = await hub.warmup("BTC/USD", "1h", 10)

    assert feed.calls == 1
    assert first == second


class _DepthFeed:
    """Candle feed whose response length reflects the requested depth.

    ``_FakeCandleFeed`` always returns a single candle, so it cannot show
    whether the hub honoured ``limit``. Timestamps ascend to the newest, which
    is what lets a slice be checked for *which* candles came back, not just how
    many.
    """

    def __init__(self) -> None:
        self.limits: list[int] = []

    def warmup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        del symbol, timeframe
        self.limits.append(limit)
        return [_c(i) for i in range(1, limit + 1)]

    def latest_closed_candle(self, symbol: str, timeframe: str) -> Candle:
        del symbol, timeframe
        return _c(1)


def _depth_hub(feed: _DepthFeed) -> MarketDataHub:
    return MarketDataHub(
        stream_feed=_FakeStream(),
        candle_feed=feed,
        limiter=RateLimiter(1000, 1000),
        mtf_cache_seconds=60.0,
        clock=lambda: 0.0,
    )


@pytest.mark.asyncio
async def test_warmup_deeper_request_refetches_at_the_greater_depth() -> None:
    """A shallow cached entry must not cap a later, deeper request (#130).

    Caching on ``(symbol, timeframe)`` alone let a 20-candle warmup poison a
    200-candle one: the second caller silently received 20 rows and a strategy
    needing 200 bars of history evaluated on a tenth of it.
    """
    feed = _DepthFeed()
    hub = _depth_hub(feed)

    shallow = await hub.warmup("BTC/USD", "1h", 20)
    deep = await hub.warmup("BTC/USD", "1h", 200)

    assert len(shallow) == 20
    assert len(deep) == 200
    assert feed.limits == [20, 200]


@pytest.mark.asyncio
async def test_warmup_shallower_request_slices_the_newest_from_cache() -> None:
    """A deep cached entry serves a shallower request without refetching (#130).

    The caller asked for the newest 20, so it must receive exactly those --
    returning all 200 hands a strategy more history than it sized itself for.
    """
    feed = _DepthFeed()
    hub = _depth_hub(feed)

    await hub.warmup("BTC/USD", "1h", 200)
    shallow = await hub.warmup("BTC/USD", "1h", 20)

    assert feed.limits == [200], "a cached deeper fetch already contains these candles"
    assert len(shallow) == 20
    # Newest, not oldest: candle 200 is the most recent bar.
    assert [candle.timestamp for candle in shallow] == list(range(181, 201))


@pytest.mark.asyncio
async def test_identical_subscribers_share_stream_and_fan_out_candles() -> None:
    """Verify that identical subscribers share a stream and receive fanned-out candles."""
    stream = _FakeStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    first: list[Candle] = []
    second: list[Candle] = []

    hub.subscribe("BTC/USD", "1m", first.append)
    hub.subscribe("BTC/USD", "1m", second.append)
    await asyncio.sleep(0)

    assert stream.run_calls == [("BTC/USD",)]
    stream.emit("BTC/USD", _c(2))
    assert first == [_c(2)]
    assert second == [_c(2)]
    assert hub.latest_price("BTC/USD", "1m") == 1.0

    hub.unsubscribe("BTC/USD", "1m", first.append)
    assert stream.stop_calls == 0
    hub.unsubscribe("BTC/USD", "1m", second.append)
    assert stream.stop_calls == 1
    hub.close()


@pytest.mark.asyncio
async def test_different_subscriptions_keep_stream_routing_isolated() -> None:
    """Verify that different subscriptions keep their stream routing isolated."""
    stream = _FakeStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    btc: list[Candle] = []
    eth: list[Candle] = []

    hub.subscribe("BTC/USD", "1m", btc.append)
    hub.subscribe("ETH/USD", "1m", eth.append)
    await asyncio.sleep(0)

    assert set(stream.run_calls) == {("BTC/USD",), ("ETH/USD",)}
    stream.emit("BTC/USD", _c(2))
    stream.emit("ETH/USD", _c(3))

    assert btc == [_c(2)]
    assert eth == [_c(3)]

    hub.unsubscribe("BTC/USD", "1m", btc.append)
    hub.unsubscribe("ETH/USD", "1m", eth.append)
    hub.close()


@pytest.mark.asyncio
async def test_duplicate_subscribe_is_ignored() -> None:
    """Verify that subscribing the same handler twice only starts one stream."""
    stream = _FakeStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    received: list[Candle] = []

    hub.subscribe("BTC/USD", "1m", received.append)
    hub.subscribe("BTC/USD", "1m", received.append)
    await asyncio.sleep(0)

    assert stream.run_calls == [("BTC/USD",)]
    stream.emit("BTC/USD", _c(2))
    assert received == [_c(2)]
    hub.unsubscribe("BTC/USD", "1m", received.append)
    hub.close()


@pytest.mark.asyncio
async def test_unsubscribe_unknown_handler_is_silent() -> None:
    """Verify that unsubscribing a handler that was never subscribed is a no-op."""
    hub = MarketDataHub(
        stream_feed=_FakeStream(),
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    hub.unsubscribe("BTC/USD", "1m", print)


def test_negative_cache_seconds_rejected() -> None:
    """Verify that a negative cache TTL is rejected."""
    with pytest.raises(ValueError):
        MarketDataHub(
            stream_feed=_FakeStream(),
            candle_feed=_FakeCandleFeed(),
            limiter=RateLimiter(1000, 1000),
            mtf_cache_seconds=-1.0,
        )


@pytest.mark.asyncio
async def test_non_keyed_stream_with_multiple_symbols_raises() -> None:
    """Verify that multi-symbol subscriptions require keyed stream handlers."""
    class _NonKeyedStream(_FakeStream):
        def on_bar_for(self, symbol: str, handler: Callable[[Candle], None]) -> None:
            del symbol, handler
            raise AttributeError

    stream = _NonKeyedStream()
    stream.on_bar_for = None  # type: ignore[assignment]
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    first_handler = print
    hub.subscribe("BTC/USD", "1m", first_handler)
    with pytest.raises(RuntimeError):
        hub.subscribe("ETH/USD", "1m", print)
    hub.unsubscribe("BTC/USD", "1m", first_handler)
    hub.close()


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_other_handlers() -> None:
    """Verify that a failing handler does not stop other handlers from receiving."""
    stream = _FakeStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    good: list[Candle] = []

    def _bad(_: Candle) -> None:
        raise RuntimeError("boom")

    hub.subscribe("BTC/USD", "1m", _bad)
    hub.subscribe("BTC/USD", "1m", good.append)
    await asyncio.sleep(0)

    stream.emit("BTC/USD", _c(2))
    assert good == [_c(2)]
    hub.unsubscribe("BTC/USD", "1m", _bad)
    hub.unsubscribe("BTC/USD", "1m", good.append)
    hub.close()


@pytest.mark.asyncio
async def test_concurrent_warmup_dedupes_single_fetch() -> None:
    """Verify concurrent warmup calls for the same key only fetch once."""
    feed = _FakeCandleFeed()
    hub = MarketDataHub(
        stream_feed=_FakeStream(),
        candle_feed=feed,
        limiter=RateLimiter(1000, 1000),
        mtf_cache_seconds=60.0,
        clock=lambda: 0.0,
    )
    results = await asyncio.gather(
        hub.warmup("BTC/USD", "1h", 10),
        hub.warmup("BTC/USD", "1h", 10),
    )
    assert feed.calls == 1
    assert results[0] == results[1]


@pytest.mark.asyncio
async def test_unexpected_stream_exit_notifies_listeners() -> None:
    """Verify a stream returning on its own notifies the degradation listeners."""
    stream = _FakeStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    seen: list[tuple[str, str, str, bool]] = []
    hub.add_stream_listener(
        lambda symbol, timeframe, reason, permanent: seen.append(
            (symbol, timeframe, reason, permanent)
        )
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await asyncio.sleep(0)
    # The feed's watch loop returns without anyone unsubscribing.
    stream.stop()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert [(s, t) for s, t, _, _ in seen] == [("BTC/USD", "1m")]
    hub.close()


@pytest.mark.asyncio
async def test_stream_error_notifies_listeners_with_the_reason() -> None:
    """Verify a stream raising reports the exception text to listeners."""

    class _BoomStream(_FakeStream):
        async def run_async(self, *symbols: str) -> None:
            del symbols
            raise RuntimeError("socket exploded")

    hub = MarketDataHub(
        stream_feed=_BoomStream(),
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    seen: list[tuple[str, str, str, bool]] = []
    hub.add_stream_listener(
        lambda symbol, timeframe, reason, permanent: seen.append(
            (symbol, timeframe, reason, permanent)
        )
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(seen) == 1
    assert "socket exploded" in seen[0][2]
    assert seen[0][3] is False, "a crashed socket is retryable, not permanent"
    hub.close()


@pytest.mark.asyncio
async def test_cancelled_stream_does_not_notify_listeners() -> None:
    """Verify unsubscribing cancels the stream without reporting degradation."""
    stream = _FakeStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    seen: list[tuple[str, str, str, bool]] = []
    listener = lambda symbol, timeframe, reason, permanent: seen.append(
        (symbol, timeframe, reason, permanent)
    )
    hub.add_stream_listener(listener)

    handler = lambda candle: None
    hub.subscribe("BTC/USD", "1m", handler)
    await asyncio.sleep(0)
    hub.unsubscribe("BTC/USD", "1m", handler)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert seen == []
    hub.remove_stream_listener(listener)
    hub.close()


@pytest.mark.asyncio
async def test_an_unsupported_capability_is_reported_as_permanent() -> None:
    """Verify a venue that cannot stream is distinguished from a broken one.

    Restarting recovers a dropped socket but can never add a capability the
    exchange does not implement (#170).
    """

    class _NotSupported(Exception):
        pass

    _NotSupported.__name__ = "NotSupported"  # ccxt's marker for missing features

    class _UnsupportedStream(_FakeStream):
        async def run_async(self, *symbols: str) -> None:
            del symbols
            raise _NotSupported("coinbase watchOHLCV() is not supported yet")

    hub = MarketDataHub(
        stream_feed=_UnsupportedStream(),
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    seen: list[tuple[str, str, str, bool]] = []
    hub.add_stream_listener(
        lambda symbol, timeframe, reason, permanent: seen.append(
            (symbol, timeframe, reason, permanent)
        )
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(seen) == 1
    assert seen[0][3] is True
    assert "not supported" in seen[0][2]
    hub.close()


@pytest.mark.asyncio
async def test_a_feed_reporting_a_gap_degrades_the_bot() -> None:
    """Verify a lossy-but-alive stream reaches the degraded signal (#171).

    A sequence gap is not a stream exit — the socket is fine and still
    delivering. Without routing it here the operator would see a healthy bot
    silently trading on incomplete candles.
    """

    class _GapStream(_FakeStream):
        def __init__(self) -> None:
            super().__init__()
            self._gap_handlers: list = []

        def on_gap(self, handler) -> None:
            self._gap_handlers.append(handler)

        def fire_gap(self, detail: str) -> None:
            for handler in tuple(self._gap_handlers):
                handler(detail)

    stream = _GapStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
    )
    seen: list[tuple[str, str, str, bool]] = []
    hub.add_stream_listener(
        lambda symbol, timeframe, reason, permanent: seen.append(
            (symbol, timeframe, reason, permanent)
        )
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await asyncio.sleep(0)
    stream.fire_gap("BTC/USD: missed 5 Coinbase message(s) (sequence 1 -> 7)")

    assert len(seen) == 1
    assert seen[0][0] == "BTC/USD"
    assert "missed 5" in seen[0][2]
    assert seen[0][3] is False, "a gap is recoverable, not a permanent limitation"
    hub.close()


# --- reconnect supervision (#117) -------------------------------------------
#
# The hub is the only place the service awaits a stream, so it is the only
# place a dropped socket can be resupervised. Before this, a Coinbase bot went
# NO DATA within minutes and stayed there for the life of the process.


async def _noop_sleep(_seconds: float) -> None:
    """Backoff that costs no wall-clock time but still yields to the loop."""
    await asyncio.sleep(0)


async def _settle(iterations: int = 40) -> None:
    """Let queued stream/reconnect callbacks run without sleeping for real."""
    for _ in range(iterations):
        await asyncio.sleep(0)


class _DroppingStream(_FakeStream):
    """A feed whose ``run_async`` returns cleanly, exactly like Coinbase's."""

    def __init__(self, drops: int) -> None:
        super().__init__()
        self._drops = drops

    async def run_async(self, *symbols: str) -> None:
        self.run_calls.append(symbols)
        if len(self.run_calls) <= self._drops:
            return  # socket closed; the old hub took this as "finished"
        await self._stopped.wait()


@pytest.mark.asyncio
async def test_stream_reconnects_after_a_clean_return() -> None:
    """Verify the hub reopens a socket that closed without an unsubscribe.

    This is the whole 24-hour-dry-run blocker: one closed socket used to end
    market data permanently.
    """
    stream = _DroppingStream(drops=3)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle()

    assert len(stream.run_calls) == 4, "expected three reconnects, then a live socket"
    hub.close()


@pytest.mark.asyncio
async def test_stream_reconnects_after_an_exception() -> None:
    """Verify a socket that raises is retried rather than abandoned."""

    class _BoomOnceStream(_FakeStream):
        async def run_async(self, *symbols: str) -> None:
            self.run_calls.append(symbols)
            if len(self.run_calls) == 1:
                raise ConnectionResetError("socket died")
            await self._stopped.wait()

    stream = _BoomOnceStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle()

    assert len(stream.run_calls) == 2
    hub.close()


@pytest.mark.asyncio
async def test_unsubscribing_stops_the_reconnect_loop() -> None:
    """Verify a stopped bot's stream is not reopened behind its back.

    Reconnecting after an unsubscribe would hold a socket, and a gap-fill,
    open for a bot that no longer exists.
    """
    stream = _DroppingStream(drops=100)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )

    handler = lambda candle: None
    hub.subscribe("BTC/USD", "1m", handler)
    await _settle(4)
    hub.unsubscribe("BTC/USD", "1m", handler)
    settled = len(stream.run_calls)
    await _settle()

    assert len(stream.run_calls) == settled, "the feed was reopened after unsubscribe"
    hub.close()


@pytest.mark.asyncio
async def test_a_permanent_failure_is_reported_once_and_not_retried() -> None:
    """Verify a venue that cannot stream is not retried in a backoff loop.

    Retrying would fail identically every time while burying the real cause
    under a stream of identical degradation events (#170).
    """

    class _NotSupported(Exception):
        pass

    _NotSupported.__name__ = "NotSupported"

    class _UnsupportedStream(_FakeStream):
        async def run_async(self, *symbols: str) -> None:
            self.run_calls.append(symbols)
            raise _NotSupported("coinbase watchOHLCV() is not supported yet")

    stream = _UnsupportedStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )
    seen: list[tuple[str, str, str, bool]] = []
    hub.add_stream_listener(
        lambda symbol, timeframe, reason, permanent: seen.append(
            (symbol, timeframe, reason, permanent)
        )
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle()

    assert len(stream.run_calls) == 1
    assert len(seen) == 1
    assert seen[0][3] is True
    hub.close()


@pytest.mark.asyncio
async def test_bars_missed_during_an_outage_are_gap_filled() -> None:
    """Verify the hub REST-fills the outage before the socket comes back.

    A 1m bot reconnecting after a 30-second gap would otherwise resume with a
    hole in its buffer that no later bar ever repairs.
    """
    fetched: list[Candle] = []

    class _HistoryFeed(_FakeCandleFeed):
        def warmup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
            del symbol, timeframe, limit
            self.calls += 1
            return [_c(10), _c(20)]

    stream = _DroppingStream(drops=1)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_HistoryFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )

    hub.subscribe("BTC/USD", "1m", fetched.append)
    await _settle()

    assert [candle.timestamp for candle in fetched] == [10, 20]
    hub.close()


@pytest.mark.asyncio
async def test_gap_fill_bypasses_the_warmup_cache() -> None:
    """Verify the refill is fresh, not the snapshot taken before the outage.

    Serving the cached warmup would hand back exactly the bars the bot already
    had and silently skip the ones it actually missed.
    """

    class _MovingFeed(_FakeCandleFeed):
        def warmup_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
            del symbol, timeframe, limit
            self.calls += 1
            return [_c(self.calls * 100)]

    feed = _MovingFeed()
    received: list[Candle] = []
    stream = _DroppingStream(drops=1)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=feed,
        limiter=RateLimiter(1000, 1000),
        mtf_cache_seconds=3600.0,  # long enough that a cache hit would be served
        sleep=_noop_sleep,
    )

    await hub.warmup("BTC/USD", "1m", 50)  # primes the cache before the outage
    hub.subscribe("BTC/USD", "1m", received.append)
    await _settle()

    assert [candle.timestamp for candle in received] == [200], "stale cache was replayed"
    hub.close()


@pytest.mark.asyncio
async def test_a_reconnect_degrades_then_recovers_on_the_next_candle() -> None:
    """Verify a recovered stream stops reporting the bot as degraded.

    Degradation is only honest while data is actually missing. Without a
    recovery signal a single overnight blip would leave the console showing a
    warning for the rest of the run.
    """
    stream = _DroppingStream(drops=1)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )
    drops: list[str] = []
    recoveries: list[tuple[str, str]] = []
    hub.add_stream_listener(
        lambda symbol, timeframe, reason, permanent: drops.append(reason)
    )
    hub.add_recovery_listener(
        lambda symbol, timeframe: recoveries.append((symbol, timeframe))
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle()
    assert len(drops) == 1, "the outage itself should be reported"
    assert recoveries == [], "nothing has arrived yet, so nothing has recovered"

    stream.emit("BTC/USD", _c(99))

    assert recoveries == [("BTC/USD", "1m")]
    hub.close()


@pytest.mark.asyncio
async def test_recovery_is_reported_once_per_outage() -> None:
    """Verify a healthy stream does not emit a recovery on every bar."""
    stream = _DroppingStream(drops=1)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )
    recoveries: list[tuple[str, str]] = []
    hub.add_recovery_listener(
        lambda symbol, timeframe: recoveries.append((symbol, timeframe))
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle()
    stream.emit("BTC/USD", _c(99))
    stream.emit("BTC/USD", _c(100))
    stream.emit("BTC/USD", _c(101))

    assert recoveries == [("BTC/USD", "1m")]
    hub.close()


@pytest.mark.asyncio
async def test_a_healthy_stream_never_reports_a_recovery() -> None:
    """Verify recovery is tied to a real outage, not emitted on the first bar."""
    stream = _FakeStream()
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )
    recoveries: list[tuple[str, str]] = []
    hub.add_recovery_listener(
        lambda symbol, timeframe: recoveries.append((symbol, timeframe))
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle(4)
    stream.emit("BTC/USD", _c(99))

    assert recoveries == []
    hub.close()


@pytest.mark.asyncio
async def test_close_cancels_the_reconnect_loop() -> None:
    """Verify a discarded hub stops reconnecting.

    Reconnection makes hub teardown mandatory. A hub dropped on credential
    rotation used to die with its stream task; now that task would keep
    reopening a socket on the superseded key forever (#137).
    """
    stream = _DroppingStream(drops=100)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle(4)
    hub.close()
    settled = len(stream.run_calls)
    await _settle()

    assert len(stream.run_calls) == settled
    assert stream.stop_calls == 1


@pytest.mark.asyncio
async def test_a_stream_with_no_subscribers_left_does_not_reconnect() -> None:
    """Verify the loop's own stop condition, not just the task cancellation.

    ``unsubscribe`` does two things: it empties the handler list *and* cancels
    the stream task. The cancellation alone is enough in the normal case, which
    means it also hides a broken stop condition — a mutation replacing that
    condition with "never stop" passes every other test here.

    Dropping the handlers without cancelling isolates the second mechanism.
    It exists so a reconnect already past its backoff cannot slip a fresh
    socket in for a bot nobody is listening to any more.
    """
    stream = _DroppingStream(drops=100)
    hub = MarketDataHub(
        stream_feed=stream,
        candle_feed=_FakeCandleFeed(),
        limiter=RateLimiter(1000, 1000),
        sleep=_noop_sleep,
    )

    hub.subscribe("BTC/USD", "1m", lambda candle: None)
    await _settle(4)
    assert len(stream.run_calls) > 1, "the loop must be reconnecting to begin with"

    hub._handlers.pop(("BTC/USD", "1m"))  # deliberately no task.cancel()
    settled = len(stream.run_calls)
    await _settle()

    assert len(stream.run_calls) == settled
    hub.close()
