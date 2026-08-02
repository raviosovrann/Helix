"""Tests for the credential-free paper venue (#116)."""

from __future__ import annotations

import pytest

from helix.models import Order, OrderType, PositionSide, Side
from helix.venues.paper import PaperVenue


def _venue(price: float | None = 100.0) -> PaperVenue:
    venue = PaperVenue()
    venue.set_price_source(lambda: price)
    return venue


def _buy(qty: float = 1.0, price: float | None = None) -> Order:
    return Order(
        symbol="BTC/USD",
        side=Side.buy,
        order_type=OrderType.market if price is None else OrderType.limit,
        qty=qty,
        price=price,
    )


def test_market_order_fills_at_the_current_mark() -> None:
    """A paper fill uses the live stream price, so the demo tracks the market."""
    result = _venue(price=250.0).place_order(_buy(qty=2.0))

    assert result.ok
    assert result.status == "filled"
    assert result.filled_qty == 2.0
    assert result.raw["avg_price"] == 250.0
    assert result.raw["paper"] is True


def test_limit_order_fills_at_its_own_price() -> None:
    """A limit order's price is the operator's instruction, not the mark."""
    result = _venue(price=250.0).place_order(_buy(qty=1.0, price=199.0))

    assert result.raw["avg_price"] == 199.0


def test_order_without_a_price_is_rejected_not_filled_at_zero() -> None:
    """A fill at zero would poison PnL, cost basis and exposure accounting.

    No price means the stream has not produced a candle yet. Refusing is
    recoverable -- the next bar supplies one -- while a zero-priced fill is
    written into the ledger permanently.
    """
    result = _venue(price=None).place_order(_buy())

    assert not result.ok
    assert result.filled_qty == 0.0
    assert result.error is not None and "price" in result.error


def test_buying_opens_a_long_position() -> None:
    """Verify that a paper buy is reflected as a long position."""
    venue = _venue(price=100.0)

    venue.place_order(_buy(qty=3.0))
    position = venue.get_position("BTC/USD")

    assert position is not None
    assert position.side is PositionSide.long
    assert position.size == 3.0
    assert position.entry_price == 100.0


def test_average_entry_price_moves_with_a_second_buy() -> None:
    """Cost basis is an average, matching how spot positions are derived (#128)."""
    venue = PaperVenue()
    venue.set_price_source(lambda: 100.0)
    venue.place_order(_buy(qty=1.0))
    venue.set_price_source(lambda: 200.0)
    venue.place_order(_buy(qty=1.0))

    position = venue.get_position("BTC/USD")

    assert position is not None
    assert position.size == 2.0
    assert position.entry_price == 150.0


def test_flat_after_selling_everything() -> None:
    """Verify that selling the whole position reports flat, not a zero-size long."""
    venue = _venue(price=100.0)
    venue.place_order(_buy(qty=1.0))

    venue.place_order(
        Order(symbol="BTC/USD", side=Side.sell, order_type=OrderType.market, qty=1.0)
    )

    assert venue.get_position("BTC/USD") is None


def test_position_is_none_when_nothing_was_ever_traded() -> None:
    """Verify that an untouched symbol reports no position."""
    assert _venue().get_position("BTC/USD") is None


def test_close_position_flattens_and_reports_the_fill() -> None:
    """Verify that closing a paper position sells it and reports the quantity."""
    venue = _venue(price=100.0)
    venue.place_order(_buy(qty=4.0))

    result = venue.close_position("BTC/USD")

    assert result.ok
    assert result.filled_qty == 4.0
    assert venue.get_position("BTC/USD") is None


def test_close_with_nothing_open_is_not_an_error() -> None:
    """Closing a flat position is a no-op, as on the real venues."""
    result = _venue().close_position("BTC/USD")

    assert result.ok
    assert result.filled_qty == 0.0
    assert result.status == "no position"


def test_close_sells_only_what_this_bot_owns() -> None:
    """Mirrors #128: a bot closes its own inventory, not everything present."""
    venue = _venue(price=100.0)
    venue.place_order(_buy(qty=5.0))

    result = venue.close_position("BTC/USD", owned_qty=2.0)

    assert result.filled_qty == 2.0
    position = venue.get_position("BTC/USD")
    assert position is not None and position.size == 3.0


def test_overselling_fills_only_the_owned_part() -> None:
    """Spot has no short (#125); overselling disposes of inventory only.

    The fill quantity is the assertion that matters, not the resulting flat
    position: both a correct 1-unit sale and a fabricated 5-unit one leave the
    book flat, but the fabricated one reports a sale that never happened into
    the ledger and credits PnL against a basis the bot never paid.
    """
    venue = _venue(price=100.0)
    venue.place_order(_buy(qty=1.0))

    result = venue.place_order(
        Order(symbol="BTC/USD", side=Side.sell, order_type=OrderType.market, qty=5.0)
    )

    assert result.filled_qty == 1.0, "only the owned unit can be sold"
    assert venue.get_position("BTC/USD") is None


def test_health_check_is_true_without_any_network() -> None:
    """The paper venue is always reachable: there is nothing to reach."""
    assert _venue().health_check() is True


def test_each_fill_gets_its_own_order_id() -> None:
    """The ledger (#135) keys on order identity, so ids must not collide."""
    venue = _venue(price=100.0)

    first = venue.place_order(_buy())
    second = venue.place_order(_buy())

    assert first.order_id != second.order_id


def test_client_order_id_is_echoed_for_the_ledger() -> None:
    """#135 stamps an idempotency key before submission; it must survive."""
    venue = _venue(price=100.0)
    order = _buy()
    order.client_order_id = "abc123"

    result = venue.place_order(order)

    assert result.raw["client_order_id"] == "abc123"


def test_paper_venue_holds_no_credentials() -> None:
    """The whole point of #116: constructing it requires nothing secret."""
    with pytest.raises(TypeError):
        PaperVenue("api-key")  # type: ignore[arg-type]
