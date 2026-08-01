"""Tests for the demo-only strategy (#119)."""

from __future__ import annotations

import pytest

from doubles import EmptyMarketData
from tradingbot.models import Action, Candle, PositionSide
from tradingbot.strategies.base import StrategyContext
from tradingbot.strategies.demo import DemoCrossoverStrategy


def _ctx(**params) -> StrategyContext:
    return StrategyContext(
        symbol="BTC/USD",
        timeframe="1m",
        quantity=0.25,
        market_data=EmptyMarketData(),
        params=params,
    )


def _candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(timestamp=i, open=c, high=c, low=c, close=c, volume=1.0)
        for i, c in enumerate(closes, start=1)
    ]


def _feed(strategy: DemoCrossoverStrategy, closes: list[float]) -> list:
    """Evaluate bar by bar against a growing buffer, as the runtime does.

    ``CandleProcessor`` calls ``on_bar`` once per closed candle with every
    candle so far, so crossover state accrues across calls. Handing the whole
    series to a single call would skip every intermediate bar -- including the
    one the strategy needs in order to know which side it was on before.
    """
    candles = _candles(closes)
    return [strategy.on_bar(candles[: i + 1]) for i in range(len(candles))]


def test_no_signal_until_there_is_enough_history() -> None:
    """A crossover is undefined before the slow average has its bars."""
    strategy = DemoCrossoverStrategy(_ctx(fast=2, slow=4))

    assert strategy.on_bar(_candles([1.0, 2.0, 3.0])) is None


def test_empty_candles_are_not_an_error() -> None:
    """The runtime evaluates on every bar, including before warmup lands."""
    assert DemoCrossoverStrategy(_ctx()).on_bar([]) is None


def test_buys_when_the_fast_average_crosses_above() -> None:
    """Verify that an upward crossover emits a long entry."""
    strategy = DemoCrossoverStrategy(_ctx(fast=2, slow=4))

    signals = _feed(strategy, [10.0, 9.0, 8.0, 7.0, 20.0])
    signal = next(s for s in signals if s is not None)

    assert signal is not None
    assert signal.action is Action.buy
    assert signal.position_side is PositionSide.long
    assert signal.symbol == "BTC/USD"
    assert signal.quantity == 0.25


def test_closes_when_the_fast_average_crosses_back_below() -> None:
    """Verify that a downward crossover closes rather than shorting.

    Closing, not selling short: the demo runs on the paper venue, which
    inherits spot's long-only capability (#125), and a strategy that emitted a
    short there would be refused before routing.
    """
    strategy = DemoCrossoverStrategy(_ctx(fast=2, slow=4))

    signals = _feed(strategy, [10.0, 9.0, 8.0, 7.0, 20.0, 1.0, 1.0])
    actions = [s.action for s in signals if s is not None]

    assert actions == [Action.buy, Action.close]


def test_signals_only_on_the_edge_not_every_bar() -> None:
    """A level test would re-enter on every bar while the fast stays above.

    That would be indistinguishable from a working strategy at a glance while
    firing an order per bar, which is exactly the behaviour a demo must not
    teach an operator to expect.
    """
    strategy = DemoCrossoverStrategy(_ctx(fast=2, slow=4))

    signals = _feed(strategy, [10.0, 9.0, 8.0, 7.0, 20.0, 21.0, 22.0])

    emitted = [s for s in signals if s is not None]
    assert len(emitted) == 1, "one crossing, one signal"
    assert emitted[0].action is Action.buy


def test_can_be_told_to_sell_instead_of_close() -> None:
    """``on_exit`` makes buy/sell/close all reachable for demonstration."""
    strategy = DemoCrossoverStrategy(_ctx(fast=2, slow=4, on_exit="sell"))

    signals = _feed(strategy, [10.0, 9.0, 8.0, 7.0, 20.0, 1.0, 1.0])
    actions = [s.action for s in signals if s is not None]

    assert actions == [Action.buy, Action.sell]


@pytest.mark.parametrize(
    "params",
    [
        {"fast": 0, "slow": 4},
        {"fast": -1, "slow": 4},
        {"fast": 4, "slow": 4},
        {"fast": 5, "slow": 4},
        {"fast": 2, "slow": 3, "on_exit": "short"},
        {"fast": "two", "slow": 4},
    ],
)
def test_invalid_params_are_refused_at_construction(params: dict) -> None:
    """Fail when the bot is started, not on the bar that would have traded."""
    with pytest.raises(ValueError):
        DemoCrossoverStrategy(_ctx(**params))


def test_defaults_work_without_any_params() -> None:
    """An operator creating a demo bot should not have to configure it."""
    strategy = DemoCrossoverStrategy(_ctx())

    # A dip then a recovery gives the fast average something to cross.
    closes = [10.0] * 10 + [1.0] * 10 + [30.0] * 10
    assert any(s is not None for s in _feed(strategy, closes))


def test_a_flat_market_exits_the_position() -> None:
    """When the averages converge, ``fast > slow`` is false and the demo exits.

    Worth pinning explicitly: a perfectly flat series makes both averages equal,
    which reads as a downward crossing rather than as "no change". The exit is
    the defensible reading -- the trend that justified the entry is gone -- but
    it is surprising enough that a fixture which plateaus will look broken.
    """
    strategy = DemoCrossoverStrategy(_ctx(fast=2, slow=4))

    signals = _feed(strategy, [10.0, 9.0, 8.0, 7.0, 20.0, 21.0, 21.0, 21.0, 21.0])
    actions = [s.action for s in signals if s is not None]

    assert actions == [Action.buy, Action.close]


def test_is_marked_demo_only() -> None:
    """The marker is what the API and supervisor refuse LIVE on (#119)."""
    assert DemoCrossoverStrategy.demo_only is True


def test_signal_names_the_strategy_unmistakably() -> None:
    """Appears in the decision log and every persisted trade row."""
    strategy = DemoCrossoverStrategy(_ctx(fast=2, slow=4))

    signals = _feed(strategy, [10.0, 9.0, 8.0, 7.0, 20.0])
    signal = next(s for s in signals if s is not None)

    assert "demo" in signal.strategy.lower()


def test_registered_under_a_name_that_cannot_be_mistaken() -> None:
    """Verify the registered name announces itself as a demo."""
    from tradingbot.strategies import available_strategies

    assert "demo-crossover" in available_strategies()
