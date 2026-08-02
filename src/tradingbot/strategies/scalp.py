"""A 1-minute mean-reversion scalper. Real candidate, unvalidated parameters.

**What this is.** A high-frequency strategy built so the console has something
to show: live decisions, filled orders, a moving position and a PnL that
changes within a session rather than once a day. Trade *frequency* was the
design target for this pass.

**What this is not.** It has not been backtested, and no claim is made here
that it is profitable. Every number below — the entry threshold, the stop, the
hold limit, the trend periods — is a starting point chosen to produce trades on
1m crypto, not a value any evidence supports yet. They stay unvalidated until
a dry run produces data to fit them against. Read the dry-run numbers before
arming this on a funded account.

It is deliberately **not** ``demo_only``. That marker (#119) means "this can
never be armed", which is the wrong statement: this strategy is untested, not
unusable, and the honest guard is an operator who has read its results.

**The rules.**

*Entry* — while flat, buy one lot when the close sits ``entry_z`` standard
deviations or more below the mean of the last ``lookback`` closes, and the
higher-timeframe trend is not down.

*Exit* — whichever comes first: price reverts to ``exit_z`` (the mean by
default); price falls ``stop_pct`` below the entry; or ``max_hold_bars`` pass.
Being stopped out starts a ``cooldown_bars`` pause, because a stop fires
exactly when the entry rule is most tempted.

**Long-only, on purpose.** The paper venue inherits spot's capabilities (#125),
where a sell disposes of inventory rather than opening a short. Exits are
``close`` rather than ``sell`` for the same reason: what a close does is
determined by the position actually held.

**Timeframe.** 1m, and not 3m: Coinbase's REST granularities are a fixed set
that has no 3m in it, so a 3m bot cannot warm up from the only credential-free
data source this project has.

**Known limitation.** The strategy tracks its own position from the signals it
emits, because ``on_bar`` is handed candles and nothing else. A rejected or
partially filled order therefore leaves its view of the position ahead of the
venue's. That is shared with every strategy here and is worth closing before
this trades real money.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from statistics import pstdev

from ..models import Action, Candle, OrderType, PositionSide, Signal
from .base import DataRequirements, StrategyContext
from .registry import strategy

_log = logging.getLogger(__name__)

TREND_TIMEFRAME = "15m"
"""Higher timeframe the entry gate is measured on.

Fixed rather than parameterised: ``DataRequirements`` is read off the *class*
before any instance exists (#130), so a per-bot timeframe could not be
declared, would never be prefetched, and would raise on the first bar.
"""

TREND_HISTORY = 60
"""Bars of ``TREND_TIMEFRAME`` prefetched — fifteen hours of context.

The ceiling for ``trend_slow`` for the same reason: the declaration is static,
so a period beyond what is declared could never be satisfied.
"""

_ZERO_SIGMA = 1e-12
"""Below this the lookback window has not moved and no z-score is meaningful."""


def _positive_int(params: Mapping, name: str, default: int, *, minimum: int = 1) -> int:
    """Read a whole-number parameter of at least ``minimum``.

    Args:
        params: Raw strategy parameters from the bot configuration.
        name: Parameter name.
        default: Value used when the parameter is absent.
        minimum: Smallest accepted value.

    Returns:
        The validated integer.

    Raises:
        ValueError: If the value is not a whole number at or above ``minimum``.
            Raised at construction so a misconfiguration stops the bot
            starting, rather than surfacing on the bar that would have traded.
    """
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be a number, got {raw!r}")
    value = int(raw)
    if value != raw or value < minimum:
        raise ValueError(f"{name} must be a whole number >= {minimum}, got {raw!r}")
    return value


def _number(params: Mapping, name: str, default: float, *, minimum: float | None = None) -> float:
    """Read a numeric parameter, optionally bounded below.

    Args:
        params: Raw strategy parameters.
        name: Parameter name.
        default: Value used when the parameter is absent.
        minimum: When set, the value must be strictly greater than this.

    Returns:
        The validated float.

    Raises:
        ValueError: If the value is not a number, or is not above ``minimum``.
    """
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be a number, got {raw!r}")
    value = float(raw)
    if minimum is not None and value <= minimum:
        raise ValueError(f"{name} must be greater than {minimum}, got {raw!r}")
    return value


@strategy("scalp-reversion")
class ScalpReversionStrategy:
    """Buy 1m dips below a rolling mean, in an uptrend, with three exits.

    Parameters (all optional):
        lookback: Bars in the mean/σ window. Default 20.
        entry_z: How many σ below the mean a close must sit to open. Default
            0.8 — chosen to trade often, not because 0.8 is right.
        exit_z: z-score at which the position is taken off. Default 0.0, the
            mean itself.
        stop_pct: Percent below the entry price that closes the position.
            Default 0.4.
        max_hold_bars: Bars after which the position is closed regardless.
            Default 20, so a stuck trade cannot eat a session.
        cooldown_bars: Bars to wait after a *stop* exit before entering again.
            Default 3.
        trend_fast: Fast SMA period on ``TREND_TIMEFRAME``. Default 8.
        trend_slow: Slow SMA period on ``TREND_TIMEFRAME``. Default 24, and at
            most ``TREND_HISTORY``.
    """

    data_requirements = DataRequirements(history={TREND_TIMEFRAME: TREND_HISTORY})
    """The 15m history the trend gate reads (#130).

    Declared on the class because the supervisor prefetches it before the bot
    starts and refreshes it on the poll tick. An undeclared timeframe is never
    kept fresh, and reading one raises rather than quietly returning nothing.
    """

    def __init__(self, ctx: StrategyContext) -> None:
        """Validate parameters and start flat.

        Args:
            ctx: Symbol, quantity, market data and strategy parameters.

        Raises:
            ValueError: If any parameter is out of range, or if ``trend_slow``
                does not exceed ``trend_fast`` or exceeds ``TREND_HISTORY``.
        """
        self.context = ctx
        params = ctx.params
        self.lookback = _positive_int(params, "lookback", 20, minimum=2)
        self.entry_z = _number(params, "entry_z", 0.8, minimum=0.0)
        self.exit_z = _number(params, "exit_z", 0.0)
        self.stop_pct = _number(params, "stop_pct", 0.4, minimum=0.0)
        self.max_hold_bars = _positive_int(params, "max_hold_bars", 20)
        self.cooldown_bars = _positive_int(params, "cooldown_bars", 3, minimum=0)
        self.trend_fast = _positive_int(params, "trend_fast", 8)
        self.trend_slow = _positive_int(params, "trend_slow", 24)
        if self.trend_slow <= self.trend_fast:
            raise ValueError(
                f"trend_slow ({self.trend_slow}) must be greater than trend_fast "
                f"({self.trend_fast}); two averages over the same window never diverge"
            )
        if self.trend_slow > TREND_HISTORY:
            raise ValueError(
                f"trend_slow ({self.trend_slow}) exceeds the {TREND_HISTORY} bars of "
                f"{TREND_TIMEFRAME} history this strategy declares, which is fixed at "
                "class level and so cannot grow per bot"
            )

        self._entry_price: float | None = None
        """Fill price of the open position, or ``None`` while flat."""

        self._bars_held = 0
        self._cooldown = 0

    def on_bar(self, candles: Sequence[Candle]) -> Signal | None:
        """Return an entry, an exit, or ``None``.

        Args:
            candles: Closed candles seen so far, oldest first.

        Returns:
            A buy, a close, or ``None`` when no rule fired.
        """
        if len(candles) < self.lookback:
            return None

        close = candles[-1].close
        window = [candle.close for candle in candles[-self.lookback:]]
        mean = sum(window) / len(window)
        sigma = pstdev(window)

        if self._entry_price is not None:
            self._bars_held += 1
            return self._exit(close, mean, sigma)

        if self._cooldown > 0:
            self._cooldown -= 1
            return None
        return self._entry(close, mean, sigma)

    def _entry(self, close: float, mean: float, sigma: float) -> Signal | None:
        """Open a long if the dip is deep enough and the trend allows it."""
        if sigma <= _ZERO_SIGMA:
            # Nothing moved all window, so there is no distribution to be cheap
            # relative to; dividing here would raise or produce an infinity.
            return None
        if (close - mean) / sigma > -self.entry_z:
            return None
        if not self._trend_is_up():
            return None

        self._entry_price = close
        self._bars_held = 0
        return self._signal(Action.buy, PositionSide.long)

    def _exit(self, close: float, mean: float, sigma: float) -> Signal | None:
        """Close the open position if any of the three exits has fired.

        Ordered by urgency, not by likelihood: the stop is checked before the
        time limit, and both before the reversion, so a bar that satisfies more
        than one leaves through the most protective.

        The trend gate is deliberately not consulted here. A filter that
        suppressed exits as well as entries would strand an open position
        exactly when getting out matters most.
        """
        entry_price = self._entry_price
        assert entry_price is not None  # guarded by the caller

        if close <= entry_price * (1.0 - self.stop_pct / 100.0):
            return self._close(stopped=True)
        if self._bars_held >= self.max_hold_bars:
            return self._close(stopped=False)
        if sigma > _ZERO_SIGMA and (close - mean) / sigma >= self.exit_z:
            return self._close(stopped=False)
        return None

    def _close(self, *, stopped: bool) -> Signal:
        """Flatten, resetting state and starting a cooldown after a stop."""
        self._entry_price = None
        self._bars_held = 0
        # Only a stop starts the pause. A reversion or time exit ended a trade
        # that behaved as designed, and pausing after those would throttle the
        # strategy for no reason.
        self._cooldown = self.cooldown_bars if stopped else 0
        return self._signal(Action.close, PositionSide.flat)

    def _signal(self, action: Action, side: PositionSide) -> Signal:
        """Build a market signal for this bot's symbol and quantity."""
        return Signal(
            strategy="scalp-reversion",
            action=action,
            symbol=self.context.symbol,
            order_type=OrderType.market,
            quantity=self.context.quantity,
            position_side=side,
        )

    def _trend_is_up(self) -> bool:
        """Whether the higher timeframe is not in a decline.

        Fails **closed**: if the declared history is unavailable or too short,
        no entry is taken. Treating missing data as "the trend is fine" would
        silently remove the only filter between a mean-reversion scalper and a
        sustained downtrend, which it would otherwise buy the whole way down.
        """
        try:
            candles = self.context.market_data.candles(
                self.context.symbol, TREND_TIMEFRAME, TREND_HISTORY
            )
        except Exception:  # noqa: BLE001 - an unreadable gate must not kill the bot
            _log.exception("scalp-reversion could not read its %s trend history", TREND_TIMEFRAME)
            return False
        closes = [candle.close for candle in candles]
        if len(closes) < self.trend_slow:
            _log.warning(
                "scalp-reversion has %d of the %d %s bars its trend filter needs; "
                "holding off entries until the history fills",
                len(closes), self.trend_slow, TREND_TIMEFRAME,
            )
            return False
        fast = sum(closes[-self.trend_fast:]) / self.trend_fast
        slow = sum(closes[-self.trend_slow:]) / self.trend_slow
        return fast >= slow
