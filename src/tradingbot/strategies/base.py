"""Strategy protocol and context used by the trading runtime."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..models import Candle, Signal


@runtime_checkable
class MarketData(Protocol):
    """Read-only, synchronous market data available to a strategy (#130).

    Deliberately narrow. It replaces a field typed ``Any`` and documented as a
    feed exposing synchronous ``warmup_candles()``, while the supervisor
    actually passed a ``MarketDataHub`` exposing **async** ``warmup()`` -- a
    mismatch no type checker could see and the no-op example strategy never
    triggered.

    Both methods are synchronous and non-blocking because strategy evaluation
    runs on a per-bot worker lane with no event loop to await on. History is
    therefore prefetched before evaluation rather than fetched on demand; see
    ``DataRequirements``.
    """

    def candles(self, symbol: str, timeframe: str, limit: int) -> Sequence[Candle]:
        """Return the newest ``limit`` closed candles, oldest first.

        Args:
            symbol: Trading symbol.
            timeframe: Candle timeframe. Must have been declared in the
                strategy's ``DataRequirements``.
            limit: Maximum number of candles wanted.

        Returns:
            At most ``limit`` candles, oldest first.

        Raises:
            MissingHistoryError: If ``timeframe`` was never prefetched.
        """
        ...

    def latest_price(self, symbol: str, timeframe: str) -> float | None:
        """Return the most recent close seen on the live stream, or ``None``."""
        ...


@dataclass(frozen=True)
class DataRequirements:
    """History a strategy needs prefetched before it is evaluated.

    Opt-in with an empty default, matching how #125 handled venue
    requirements: a strategy that reads only the candles handed to ``on_bar``
    declares nothing and costs nothing.

    Declaring history up front is what keeps ``MarketData`` synchronous. The
    runtime knows every timeframe a strategy needs before it starts, so it can
    fetch them on the event loop through the shared rate limiter instead of
    pushing async into every strategy author's problem space.
    """

    history: Mapping[str, int] = field(default_factory=dict)
    """Timeframe -> number of bars, e.g. ``{"30m": 200, "4h": 50}``."""


@dataclass(frozen=True)
class StrategyContext:
    """Runtime configuration supplied to every strategy instance."""

    symbol: str
    """Trading symbol, e.g. ``BTC/USD``."""

    timeframe: str
    """Candle timeframe, e.g. ``1h``."""

    quantity: float
    """Default order quantity for the strategy."""

    market_data: MarketData
    """Prefetched market data the strategy can read synchronously.

    Renamed from ``data_feed`` (typed ``Any``) rather than retyped in place:
    the old name promised a feed with a different, synchronous fetch method, so
    keeping it would have left working-looking call sites that never worked.
    """

    params: dict[str, Any]
    """Strategy-specific parameters from the bot configuration."""


@runtime_checkable
class Strategy(Protocol):
    """Protocol implemented by every trade strategy."""

    def on_bar(self, candles: Sequence[Candle]) -> Signal | None:
        """Generate a trading signal from the latest closed bar(s).

        Args:
            candles: Closed candles seen so far, ordered oldest-first.

        Returns:
            A signal to route, or ``None`` when no action is taken.
        """
        ...

