"""A paper fill's price must survive into the ledger (found by the dry run).

The ledger read the fill price from ``raw["average"]`` — ccxt's spelling, since
a ccxt result passes the exchange response through verbatim. ``PaperVenue``
wrote ``raw["avg_price"]``, its own invention. The two never met, so every
paper fill was recorded at ``order.price``, which on a *market* order is
``None``.

Nothing failed loudly. Downstream, a fill priced at zero-or-missing is skipped
by the spot position projection, so on the credential-free demo path — the one
the whole demo runs on — position, cost basis, realised PnL and notional
exposure were all permanently dead, and the console read ``0.00 collecting…``
for as long as you cared to watch it.

The fix makes the fill price a typed field on ``OrderResult`` instead of a
key in a venue-specific blob, so the next venue cannot silently pick a third
spelling.
"""

from __future__ import annotations

from helix.models import Order, OrderResult, OrderType, Side
from helix.service.ledger import OrderLedger, events_from_result, events_from_status
from helix.service.positions import spot_position
from helix.venues.paper import PaperVenue


def _market_buy(qty: float = 0.01) -> Order:
    return Order(
        symbol="BTC/USD",
        side=Side.buy,
        order_type=OrderType.market,
        qty=qty,
        price=None,
        client_order_id="cid-1",
    )


def _paper_at(price: float) -> PaperVenue:
    venue = PaperVenue()
    venue.set_price_source(lambda: price)
    return venue


def test_a_paper_market_fill_reports_the_price_it_filled_at() -> None:
    """Verify the venue puts the fill price on the typed field.

    It was only ever in ``raw``, under a name nothing downstream read.
    """
    result = _paper_at(50_000.0).place_order(_market_buy())

    assert result.ok
    assert result.avg_price == 50_000.0


def test_a_paper_close_reports_the_price_it_filled_at() -> None:
    """Verify the exit carries a price too, or realised PnL cannot be computed."""
    venue = _paper_at(50_000.0)
    venue.place_order(_market_buy())
    venue.set_price_source(lambda: 51_000.0)

    result = venue.close_position("BTC/USD")

    assert result.ok
    assert result.avg_price == 51_000.0


def test_the_ledger_records_the_paper_fill_price() -> None:
    """Verify the price reaches the persisted lifecycle events.

    This is the seam that was broken: the venue knew the price, the ledger
    asked for a key the venue never wrote, and the fill was recorded at the
    market order's ``price`` — which is ``None``.
    """
    order = _market_buy()
    result = _paper_at(50_000.0).place_order(order)

    events = events_from_result(order, result, bot_id="bot-1", ts=1)
    fills = [event for event in events if event["kind"] == "order_status"]

    assert len(fills) == 1
    assert fills[0]["avg_price"] == 50_000.0


def test_a_ccxt_style_average_is_still_read() -> None:
    """Verify the exchange's own spelling keeps working.

    A live ccxt result is the exchange response passed through verbatim, so
    ``average`` is where the price genuinely is. The typed field must not
    displace it.
    """
    order = _market_buy()
    result = OrderResult(
        ok=True,
        order_id="x-1",
        status="closed",
        filled_qty=0.01,
        raw={"average": 49_500.0},
    )

    events = events_from_result(order, result, bot_id="bot-1", ts=1)
    fills = [event for event in events if event["kind"] == "order_status"]

    assert fills[0]["avg_price"] == 49_500.0


def test_a_round_trip_on_the_paper_venue_produces_a_position_then_realised_pnl() -> None:
    """Verify the whole chain the console reads from, end to end.

    Every unit below this passed while the console showed a flat position and
    a PnL of zero for hours, because each one was correct about the wrong
    number. Asserting on the projection is what closes that gap.
    """
    venue = _paper_at(50_000.0)
    ledger = OrderLedger()

    buy = _market_buy()
    for event in events_from_result(buy, venue.place_order(buy), bot_id="bot-1", ts=1):
        ledger.apply(event)

    holding = spot_position(ledger.orders(bot_id="bot-1"))
    assert holding.is_flat is False, "the bot holds 0.01 BTC and the console must say so"
    assert holding.quantity == 0.01
    assert holding.average_cost == 50_000.0
    assert holding.realized_pnl == 0.0

    venue.set_price_source(lambda: 51_000.0)
    sell = Order(
        symbol="BTC/USD",
        side=Side.sell,
        order_type=OrderType.market,
        qty=0.01,
        price=None,
        client_order_id="cid-2",
    )
    for event in events_from_result(sell, venue.place_order(sell), bot_id="bot-1", ts=1):
        ledger.apply(event)

    closed = spot_position(ledger.orders(bot_id="bot-1"))
    assert closed.is_flat is True
    assert closed.realized_pnl == 10.0, "0.01 BTC bought at 50k and sold at 51k is $10"


def test_a_zero_fill_price_is_not_treated_as_a_real_price() -> None:
    """Verify a zero never becomes cost basis.

    A venue that reports ``0`` has told us nothing, but a zero-priced fill is
    arithmetically valid: it makes the buy look free, and every number derived
    from it — average cost, realised PnL, notional exposure — is wrong in the
    same direction and stays wrong permanently.
    """
    order = Order(
        symbol="BTC/USD",
        side=Side.buy,
        order_type=OrderType.limit,
        qty=0.01,
        price=49_000.0,
        client_order_id="cid-1",
    )
    result = OrderResult(
        ok=True, order_id="x-1", status="closed", filled_qty=0.01, avg_price=0.0, raw={}
    )

    events = events_from_result(order, result, bot_id="bot-1", ts=1)
    fills = [event for event in events if event["kind"] == "order_status"]

    assert fills[0]["avg_price"] == 49_000.0, "a zero must fall through to the limit price"


def test_a_polled_fill_also_carries_the_typed_price() -> None:
    """Verify the reconciliation path reads the price too.

    Fills are discovered two ways: from the submission response, and from the
    poll that chases orders the venue knows more about than we do (#135). Only
    fixing the first would leave any fill discovered late priceless, which is
    the same silent hole in a rarer path.
    """
    result = OrderResult(
        ok=True, order_id="x-1", status="closed", filled_qty=0.01, avg_price=50_500.0, raw={}
    )

    events = events_from_status("cid-1", result, ts=1)
    fills = [event for event in events if event["kind"] == "order_status"]

    assert len(fills) == 1
    assert fills[0]["avg_price"] == 50_500.0
