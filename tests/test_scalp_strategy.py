"""Tests for the 1m mean-reversion scalper.

The strategy is a real candidate rather than a demo, so these cover the trade
*rules* — entry, both exits, the cooldown and the trend gate — not merely that
signals appear.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from helix.models import Action, Candle, PositionSide
from helix.strategies import DataRequirements, StrategyContext, build_strategy
from helix.strategies.registry import (
    available_strategies,
    is_demo_strategy,
    strategy_data_requirements,
)
from helix.strategies.scalp import TREND_HISTORY, TREND_TIMEFRAME, ScalpReversionStrategy

_MINUTE = 60_000


def _candle(close: float, index: int = 0) -> Candle:
    return Candle(
        timestamp=index * _MINUTE,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
    )


def _series(closes: Sequence[float]) -> list[Candle]:
    return [_candle(close, index) for index, close in enumerate(closes)]


class _TrendData:
    """A ``MarketData`` serving one higher-timeframe series.

    Defaults to a clean uptrend so a test that is not about the trend gate does
    not have to set one up.
    """

    def __init__(self, closes: Sequence[float] | None = None) -> None:
        if closes is None:
            closes = [100.0 + i for i in range(TREND_HISTORY)]
        self.closes = list(closes)
        self.reads: list[tuple[str, str, int]] = []

    def candles(self, symbol: str, timeframe: str, limit: int) -> Sequence[Candle]:
        self.reads.append((symbol, timeframe, limit))
        return _series(self.closes)[-limit:]

    def latest_price(self, symbol: str, timeframe: str) -> float | None:
        del symbol, timeframe
        return self.closes[-1] if self.closes else None


def _downtrend() -> _TrendData:
    return _TrendData([200.0 - i for i in range(TREND_HISTORY)])


def _context(market_data=None, **params) -> StrategyContext:
    return StrategyContext(
        symbol="BTC/USD",
        timeframe="1m",
        quantity=0.01,
        market_data=market_data if market_data is not None else _TrendData(),
        params=params,
    )


def _strategy(market_data=None, **params) -> ScalpReversionStrategy:
    return ScalpReversionStrategy(_context(market_data, **params))


# A 20-bar base that is perfectly flat except for controlled moves appended by
# each test. Flat means the rolling mean is exactly 100 and sigma is 0 until a
# test moves the price, which keeps the expected z-scores easy to reason about.
def _flat(n: int = 20, price: float = 100.0) -> list[float]:
    return [price] * n


# --- registration and contract ----------------------------------------------


def test_the_scalper_is_registered_and_is_not_demo_only() -> None:
    """Verify it is a real candidate, not a demo (#119's marker must be absent).

    ``demo_only`` blocks a strategy from ever being armed. This one is
    unvalidated, not unusable, so the marker would be the wrong statement — the
    honest guard on arming it is the operator reading the dry-run numbers.
    """
    assert "scalp-reversion" in available_strategies()
    assert is_demo_strategy("scalp-reversion") is False


def test_it_declares_the_higher_timeframe_history_it_reads() -> None:
    """Verify the declared requirements match what the trend gate actually reads.

    Requirements are read off the class before the bot starts (#130), so an
    undeclared timeframe is never prefetched and never refreshed — the gate
    would raise ``MissingHistoryError`` on the first bar.
    """
    declared = strategy_data_requirements("scalp-reversion")

    assert isinstance(declared, DataRequirements)
    assert declared.history == {TREND_TIMEFRAME: TREND_HISTORY}


def test_the_trading_timeframe_is_one_coinbase_actually_serves() -> None:
    """Verify the documented timeframe is accepted by the credential-free feed.

    Coinbase's REST granularities are a fixed set; ``3m`` is rejected outright,
    so a 3m scalper could not run on the only keyless data source there is.
    """
    from helix.coinbase_feed import bucket_seconds

    assert bucket_seconds("1m") == 60
    assert bucket_seconds(TREND_TIMEFRAME) == 900


def test_it_reads_its_declared_timeframe_for_its_own_symbol() -> None:
    """Verify the gate reads the declared timeframe, not the trading one."""
    data = _TrendData()
    strategy = _strategy(data)

    strategy.on_bar(_series(_flat() + [97.0]))

    assert data.reads, "the trend gate never consulted market data"
    assert {timeframe for _, timeframe, _ in data.reads} == {TREND_TIMEFRAME}
    assert {symbol for symbol, _, _ in data.reads} == {"BTC/USD"}


# --- entry -------------------------------------------------------------------


def test_no_signal_before_there_is_enough_history() -> None:
    """Verify a short buffer produces no trade rather than a noisy one.

    The buffer here holds a dip deep enough to trade on, so the refusal comes
    from the bar count and not from the flat-market guard — nineteen identical
    closes would be rejected for having no volatility whatever the count rule
    said.
    """
    strategy = _strategy(lookback=20)

    assert strategy.on_bar(_series(_flat(18) + [95.0])) is None


def test_it_buys_a_dip_below_the_rolling_mean() -> None:
    """Verify a close far enough below the mean opens a long."""
    strategy = _strategy(lookback=20, entry_z=1.0)

    # 19 flat bars then a drop: the drop is many sigma below the mean.
    signal = strategy.on_bar(_series(_flat(19) + [95.0]))

    assert signal is not None
    assert signal.action is Action.buy
    assert signal.position_side is PositionSide.long
    assert signal.symbol == "BTC/USD"
    assert signal.quantity == 0.01
    assert signal.strategy == "scalp-reversion"


def test_a_shallow_dip_does_not_trigger_an_entry() -> None:
    """Verify the entry threshold is a real filter, not decoration."""
    strategy = _strategy(lookback=20, entry_z=1.0)

    # Alternating 100/101 gives sigma ~0.49; a close of 100.25 sits about half
    # a sigma below the mean, comfortably inside the 1σ threshold.
    closes = [100.0 if i % 2 else 101.0 for i in range(19)] + [100.25]
    assert strategy.on_bar(_series(closes)) is None


def test_it_does_not_buy_again_while_already_long() -> None:
    """Verify a sustained dip opens one position, not one per bar.

    A level test rather than a position-aware one would fire an entry on every
    bar the price stayed cheap, which looks like conviction and is really just
    the same trade submitted repeatedly.
    """
    strategy = _strategy(lookback=20, entry_z=1.0)
    closes = _flat(19) + [95.0]

    first = strategy.on_bar(_series(closes))
    second = strategy.on_bar(_series(closes + [95.0]))

    assert first is not None and first.action is Action.buy
    assert second is None


def test_a_flat_market_produces_no_signal_and_no_division_error() -> None:
    """Verify zero volatility is handled, since sigma is the divisor.

    A market that has not moved for the whole lookback is unusual but real on
    an illiquid pair, and it must not take the bot down.
    """
    strategy = _strategy(lookback=20)

    assert strategy.on_bar(_series(_flat(25))) is None


# --- exits -------------------------------------------------------------------


def _enter(strategy: ScalpReversionStrategy) -> list[float]:
    """Open a position and return the close series that did it."""
    closes = _flat(19) + [95.0]
    signal = strategy.on_bar(_series(closes))
    assert signal is not None and signal.action is Action.buy
    return closes


def test_it_closes_when_price_reverts_to_the_mean() -> None:
    """Verify the profit-taking exit: the reversion the entry bet on."""
    strategy = _strategy(lookback=20, entry_z=1.0, exit_z=0.0)
    closes = _enter(strategy)

    signal = strategy.on_bar(_series(closes + [101.0]))

    assert signal is not None
    assert signal.action is Action.close
    assert signal.position_side is PositionSide.flat


def test_it_closes_on_the_stop_when_the_dip_keeps_going() -> None:
    """Verify the loss is bounded rather than left to the reversion exit.

    Without this the position is held until price returns to a mean that is
    itself falling, which is how a scalp becomes an investment.
    """
    strategy = _strategy(lookback=20, entry_z=1.0, stop_pct=0.5)
    closes = _enter(strategy)  # entered at 95.0

    # 0.5% below 95.0 is 94.525.
    assert strategy.on_bar(_series(closes + [94.6])) is None
    signal = strategy.on_bar(_series(closes + [94.6, 94.5]))

    assert signal is not None
    assert signal.action is Action.close


def test_it_closes_after_the_maximum_hold() -> None:
    """Verify a position cannot be held indefinitely waiting for a reversion.

    The time stop is what makes turnover predictable: without it a bot can sit
    in one trade for a whole session and show nothing.
    """
    strategy = _strategy(lookback=20, entry_z=1.0, max_hold_bars=3, stop_pct=50.0)
    closes = _enter(strategy)

    # Held flat, so neither the reversion exit nor the stop can fire.
    assert strategy.on_bar(_series(closes + [95.0])) is None
    assert strategy.on_bar(_series(closes + [95.0] * 2)) is None
    signal = strategy.on_bar(_series(closes + [95.0] * 3))

    assert signal is not None
    assert signal.action is Action.close


def test_it_can_trade_again_after_a_reversion_exit() -> None:
    """Verify closing resets the state, so the bot keeps trading all day."""
    strategy = _strategy(lookback=20, entry_z=1.0, exit_z=0.0, cooldown_bars=0)
    closes = _enter(strategy)
    exited = strategy.on_bar(_series(closes + [101.0]))
    assert exited is not None

    # A fresh dip, measured against the now-wider distribution.
    signal = strategy.on_bar(_series(closes + [101.0, 90.0]))

    assert signal is not None
    assert signal.action is Action.buy


# --- cooldown ----------------------------------------------------------------


def test_a_stop_exit_starts_a_cooldown_before_re_entering() -> None:
    """Verify the bot does not re-buy the bar after being stopped out.

    A stop fires precisely when price is far below the mean, which is also
    exactly when the entry rule is most tempted. Re-entering immediately turns
    one bad trade into a sequence of them.
    """
    strategy = _strategy(lookback=20, entry_z=1.0, stop_pct=0.5, cooldown_bars=2)
    closes = _enter(strategy)
    stopped = strategy.on_bar(_series(closes + [90.0]))
    assert stopped is not None and stopped.action is Action.close

    assert strategy.on_bar(_series(closes + [90.0, 89.0])) is None
    assert strategy.on_bar(_series(closes + [90.0, 89.0, 88.0])) is None
    signal = strategy.on_bar(_series(closes + [90.0, 89.0, 88.0, 87.0]))

    assert signal is not None
    assert signal.action is Action.buy


def test_a_reversion_exit_does_not_start_a_cooldown() -> None:
    """Verify the cooldown answers a stop, not every exit.

    Pausing after a winning reversion would throttle the strategy for no
    reason: nothing went wrong on that trade.
    """
    strategy = _strategy(lookback=20, entry_z=1.0, exit_z=0.0, cooldown_bars=5)
    closes = _enter(strategy)
    exited = strategy.on_bar(_series(closes + [101.0]))
    assert exited is not None and exited.action is Action.close

    signal = strategy.on_bar(_series(closes + [101.0, 90.0]))

    assert signal is not None, "a winning exit must not pause the strategy"


# --- higher-timeframe trend gate --------------------------------------------


def test_it_does_not_buy_dips_in_a_higher_timeframe_downtrend() -> None:
    """Verify the declared 15m history is used to refuse falling knives.

    Every bar of a sustained decline is a dip below its own short mean, so an
    ungated mean-reversion scalper buys the whole way down.
    """
    strategy = _strategy(_downtrend(), lookback=20, entry_z=1.0)

    assert strategy.on_bar(_series(_flat(19) + [95.0])) is None


def test_it_still_exits_during_a_downtrend() -> None:
    """Verify the gate blocks entries only.

    A filter that also suppressed exits would strand an open position exactly
    when getting out matters most.
    """
    strategy = _strategy(lookback=20, entry_z=1.0, stop_pct=0.5)
    closes = _enter(strategy)
    strategy.context.market_data.closes = [200.0 - i for i in range(TREND_HISTORY)]

    signal = strategy.on_bar(_series(closes + [90.0]))

    assert signal is not None
    assert signal.action is Action.close


def test_entries_stop_when_the_trend_history_is_too_short() -> None:
    """Verify a gate that cannot be evaluated refuses the trade.

    Treating absent history as "trend is fine" would silently disable the one
    filter standing between this strategy and a downtrend.
    """
    strategy = _strategy(_TrendData([100.0] * 5), lookback=20, entry_z=1.0)

    assert strategy.on_bar(_series(_flat(19) + [95.0])) is None


# --- parameter validation ----------------------------------------------------


@pytest.mark.parametrize(
    "params, message",
    [
        ({"lookback": 1}, "lookback"),
        ({"lookback": 2.5}, "lookback"),
        ({"entry_z": 0.0}, "entry_z"),
        ({"entry_z": -1.0}, "entry_z"),
        ({"stop_pct": 0.0}, "stop_pct"),
        ({"max_hold_bars": 0}, "max_hold_bars"),
        ({"cooldown_bars": -1}, "cooldown_bars"),
        ({"trend_fast": 30, "trend_slow": 30}, "trend_slow"),
        ({"trend_slow": TREND_HISTORY + 1}, "trend_slow"),
    ],
)
def test_bad_parameters_are_refused_at_construction(params: dict, message: str) -> None:
    """Verify a misconfiguration stops the bot starting, not the bar that trades."""
    with pytest.raises(ValueError, match=message):
        _strategy(**params)


def test_it_builds_through_the_registry() -> None:
    """Verify the registered factory produces a working instance."""
    strategy = build_strategy("scalp-reversion", _context())

    assert strategy.on_bar(_series(_flat(19) + [95.0])) is not None
