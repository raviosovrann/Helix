"""DEMONSTRATION-ONLY strategy. Not a trading strategy. Never run this live.

The only registered strategy was ``example``, which returns ``None``
unconditionally, so a started bot showed "no signal" forever and an operator
could not observe signal routing, dry-run orders, trade persistence, PnL or
risk blocking without first writing a strategy (#119).

This fills that gap and nothing else. It is a two-moving-average crossover with
no risk management, no position sizing, no filtering and no regard for cost --
the textbook example that exists to be legible, not profitable. It is here so
that the *plumbing* can be watched end to end on real market data.

The production long/short strategy is a separate design question tracked in
#78. Do not grow this one into it: the marker below is what stops this module
being armed, and a strategy that deserved to trade would have to lose it.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..models import Action, Candle, OrderType, PositionSide, Signal
from .base import StrategyContext
from .registry import strategy

_EXIT_ACTIONS = {"close": Action.close, "sell": Action.sell}


def _positive_int(params: dict, name: str, default: int) -> int:
    """Read a strictly positive integer parameter.

    Args:
        params: Raw strategy parameters from the bot configuration.
        name: Parameter name.
        default: Value used when the parameter is absent.

    Returns:
        The validated integer.

    Raises:
        ValueError: If the value is not a whole number greater than zero.
            Raised at construction so a misconfiguration stops the bot
            starting, rather than surfacing on the bar that would have traded.
    """
    raw = params.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{name} must be a number, got {raw!r}")
    value = int(raw)
    if value != raw or value <= 0:
        raise ValueError(f"{name} must be a whole number > 0, got {raw!r}")
    return value


@strategy("demo-crossover")
class DemoCrossoverStrategy:
    """DEMO ONLY -- a moving-average crossover, for watching the plumbing work.

    Emits a buy when the fast average crosses **above** the slow one, and exits
    when it crosses back below. Signals fire on the crossing itself, not while
    the averages stay apart: a level test would fire an order every bar for as
    long as the fast average stayed above, which looks like a working strategy
    at a glance and is the habit a demo must not teach.

    Parameters (all optional):
        fast: Fast average period. Default 3.
        slow: Slow average period, must exceed ``fast``. Default 8.
        on_exit: ``"close"`` (default) or ``"sell"``. Both are offered so a
            demo can show all three signal actions; there is deliberately no
            short, because the paper venue inherits spot's long-only
            capability (#125) and a short would be refused before routing.
    """

    demo_only = True
    """Refuses to be armed. Read by the API and the supervisor (#119).

    A demo strategy reaching a funded account is the one failure this module
    could cause, so the block lives on the class rather than in a name check
    somewhere that could be forgotten when the strategy is renamed.
    """

    def __init__(self, ctx: StrategyContext) -> None:
        """Validate parameters and prepare crossover state.

        Args:
            ctx: Symbol, quantity and strategy parameters.

        Raises:
            ValueError: If the periods are not positive whole numbers, if
                ``slow`` does not exceed ``fast``, or if ``on_exit`` is not
                one of ``close``/``sell``.
        """
        self.context = ctx
        self.fast = _positive_int(ctx.params, "fast", 3)
        self.slow = _positive_int(ctx.params, "slow", 8)
        if self.slow <= self.fast:
            raise ValueError(
                f"slow ({self.slow}) must be greater than fast ({self.fast}); "
                "two averages over the same window never cross"
            )
        exit_name = str(ctx.params.get("on_exit", "close"))
        if exit_name not in _EXIT_ACTIONS:
            raise ValueError(
                f"on_exit must be one of {sorted(_EXIT_ACTIONS)}, got {exit_name!r}"
            )
        self.exit_action = _EXIT_ACTIONS[exit_name]
        self._fast_above: bool | None = None
        """Whether the fast average was above on the previous evaluated bar.

        ``None`` until the first bar with enough history, so the very first
        comparison cannot be read as a crossing -- a bot started into a market
        already trending up would otherwise buy immediately on nothing.
        """

    def on_bar(self, candles: Sequence[Candle]) -> Signal | None:
        """Return a signal when the averages cross, otherwise ``None``.

        Args:
            candles: Closed candles seen so far, oldest first.

        Returns:
            A buy on an upward crossing, the configured exit on a downward
            one, or ``None`` when there is no crossing or not enough history.
        """
        if len(candles) < self.slow:
            return None

        closes = [candle.close for candle in candles]
        fast_avg = sum(closes[-self.fast:]) / self.fast
        slow_avg = sum(closes[-self.slow:]) / self.slow
        fast_above = fast_avg > slow_avg

        previous, self._fast_above = self._fast_above, fast_above
        if previous is None or previous == fast_above:
            return None

        action = Action.buy if fast_above else self.exit_action
        return Signal(
            strategy="demo-crossover",
            action=action,
            symbol=self.context.symbol,
            order_type=OrderType.market,
            quantity=self.context.quantity,
            position_side=PositionSide.long if fast_above else PositionSide.flat,
        )
