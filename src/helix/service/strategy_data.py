"""Adapter presenting a ``MarketDataHub`` as the strategy ``MarketData`` contract.

The hub is async and shared across bots; strategies are synchronous and run on
a per-bot worker lane. This module is the seam between the two: it prefetches
every timeframe a strategy declared, on the event loop and through the hub's
shared rate limiter, then serves those candles synchronously from memory.

Doing it this way keeps rate limiting and caching in one place. A strategy that
fetched its own history would bypass the limiter and the shared cache, which is
exactly the "bypass the intended rate-limited data path" failure in #130.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from ..models import Candle
from ..strategies.base import DataRequirements


class MissingHistoryError(LookupError):
    """Raised when a strategy reads a timeframe it never declared.

    Returning an empty list instead would be indistinguishable from a quiet
    market: the strategy would keep running and quietly stop taking the trades
    it was written to take.
    """


class HubMarketData:
    """Synchronous, prefetched view of one bot's market data.

    One instance per bot. It holds only that bot's declared timeframes, so a
    strategy cannot accidentally read history nobody arranged to keep fresh.
    """

    def __init__(self, hub: Any, *, symbol: str) -> None:
        """Bind the adapter to a hub and the bot's symbol.

        Args:
            hub: The shared ``MarketDataHub``. Typed loosely because the hub
                imports from the supervisor, and importing it here would close
                the cycle.
            symbol: The bot's trading symbol. Reads for any other symbol are
                refused -- a bot's data requirements are declared for the
                instrument it trades.
        """
        self._hub = hub
        self._symbol = symbol
        self._history: dict[str, list[Candle]] = {}

    async def prefetch(self, requirements: DataRequirements) -> None:
        """Fetch (or refresh) every declared timeframe.

        Called once before the bot starts and again on the supervisor's poll
        tick, because a higher timeframe goes stale while the bot's own
        timeframe keeps streaming. Caching and rate limiting belong to the hub,
        so this always asks and lets the hub decide whether a fetch is needed.

        Args:
            requirements: The strategy's declared history.
        """
        if not requirements.history:
            return
        timeframes = sorted(requirements.history)
        fetched = await asyncio.gather(
            *(self._hub.warmup(self._symbol, tf, requirements.history[tf]) for tf in timeframes)
        )
        for timeframe, candles in zip(timeframes, fetched):
            self._history[timeframe] = list(candles)

    def candles(self, symbol: str, timeframe: str, limit: int) -> Sequence[Candle]:
        """Return the newest ``limit`` prefetched candles, oldest first.

        Args:
            symbol: Trading symbol; must be the bot's own.
            timeframe: A timeframe declared in the strategy's requirements.
            limit: Maximum number of candles wanted.

        Returns:
            At most ``limit`` candles, oldest first.

        Raises:
            MissingHistoryError: If ``symbol`` is not this bot's, or
                ``timeframe`` was never declared and so is never refreshed.
        """
        if symbol != self._symbol:
            raise MissingHistoryError(
                f"{symbol!r} is not this bot's symbol ({self._symbol!r}); "
                "a bot only prefetches history for the instrument it trades"
            )
        try:
            history = self._history[timeframe]
        except KeyError as exc:
            declared = ", ".join(sorted(self._history)) or "none"
            raise MissingHistoryError(
                f"timeframe {timeframe!r} was not declared in the strategy's "
                f"DataRequirements (declared: {declared}), so no history is "
                "prefetched or kept fresh for it"
            ) from exc
        return history[-limit:]

    def latest_price(self, symbol: str, timeframe: str) -> float | None:
        """Return the most recent close seen on the live stream, or ``None``.

        Delegates to the hub rather than reading the prefetched snapshot: the
        snapshot is warmup history, which lags the stream by up to a full bar.
        """
        return self._hub.latest_price(symbol, timeframe)
