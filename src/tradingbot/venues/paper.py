"""Credential-free paper execution venue (#116).

The product promises dry-run validation before funding, but the venue registry
refused to build a ccxt venue without ``api_key``/``api_secret`` even when
``live=False``, so a new operator could not start a dry-run bot at all.

This venue closes that gap. It simulates *fills* in memory and never opens a
socket, so it needs no credentials and cannot reach a private account or order
endpoint -- there is no client here to reach one with. Market data is separate
and genuinely live: Coinbase's public candle and trade feeds need no keys, so a
paper bot watches the real market and only its executions are simulated.

It is deliberately a **separate venue**, not a mode of the live one. Relaxing
the credential check on the real venue when ``live=False`` would make the
credential-free case a branch inside the code path that can reach an exchange,
which is the shape most likely to let a misconfiguration through.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

from ..models import Order, OrderResult, OrderType, Position, PositionSide, Side

_QTY_EPSILON = 1e-9
"""Below this a position is flat.

Float fills rarely sum back to exactly zero, and a 1e-12 residue reported as an
open position would keep a closed bot looking exposed forever -- the same
reasoning as the ledger's epsilon (#135).
"""


class PaperVenue:
    """Simulated spot execution against live prices, with no credentials.

    Holds one average-cost position per symbol. Average cost rather than FIFO,
    matching how real spot positions are derived from the order log in #128, so
    the number an operator sees in the demo is computed the same way as the one
    they will see on a funded account.
    """

    def __init__(self) -> None:
        """Create an empty paper account.

        Takes no arguments at all: a credential passed here would be silently
        ignored, and a venue that accepts secrets it never uses invites the
        belief that it authenticates something.
        """
        self._positions: dict[str, tuple[float, float]] = {}
        """symbol -> (quantity, average cost)."""

        self._price_source: Callable[[], float | None] = lambda: None
        self._ids = itertools.count(1)

    def set_price_source(self, price_source: Callable[[], float | None]) -> None:
        """Attach the live mark used to fill market orders.

        Detected and called by the supervisor, which owns the market-data hub;
        the venue registry builds venues from credentials alone and has no hub
        to hand over. Same optional-capability pattern as ``contract_spec`` and
        ``owned_qty`` (#124, #128).

        Args:
            price_source: Returns the latest close, or ``None`` before the
                first candle arrives.
        """
        self._price_source = price_source

    def place_order(self, order: Order) -> OrderResult:
        """Fill ``order`` immediately at the mark, and update the position.

        Paper fills are immediate and complete. A partial-fill simulation would
        be inventing venue behaviour rather than demonstrating ours, and the
        ledger already has real partial-fill handling exercised against the
        live adapters (#135).

        Args:
            order: The order to simulate.

        Returns:
            ``filled`` with the simulated price, or a rejection when no price
            is known yet.
        """
        price = order.price if order.order_type is OrderType.limit else self._price_source()
        if price is None:
            # No candle has arrived yet. Refusing is recoverable -- the next
            # bar supplies a price -- whereas a zero-priced fill is written
            # into the ledger permanently and corrupts cost basis, PnL and
            # exposure at once.
            return OrderResult(
                ok=False,
                order_id=None,
                status="rejected",
                filled_qty=0.0,
                raw={"paper": True},
                error=(
                    "no market price available yet; the paper venue fills at the "
                    "latest streamed close and no candle has arrived"
                ),
            )

        filled = self._apply(order.symbol, order.side, order.qty, price)
        return OrderResult(
            ok=True,
            order_id=f"paper-{next(self._ids)}",
            status="filled",
            filled_qty=filled,
            raw={
                "paper": True,
                "avg_price": price,
                "client_order_id": order.client_order_id,
            },
        )

    def close_position(self, symbol: str, owned_qty: float | None = None) -> OrderResult:
        """Sell out of ``symbol``, optionally only the part this bot owns.

        Args:
            symbol: Symbol to flatten.
            owned_qty: When given, sell only this much -- a spot bot owns only
                what it bought, not everything in the account (#128).

        Returns:
            The simulated closing fill, or a flat ``no position`` result.
        """
        held, _ = self._positions.get(symbol, (0.0, 0.0))
        quantity = held if owned_qty is None else min(held, owned_qty)
        if quantity <= _QTY_EPSILON:
            return OrderResult(
                ok=True,
                order_id=None,
                status="no position",
                filled_qty=0.0,
                raw={"paper": True},
            )

        price = self._price_source()
        if price is None:
            return OrderResult(
                ok=False,
                order_id=None,
                status="rejected",
                filled_qty=0.0,
                raw={"paper": True},
                error="no market price available yet; cannot value a paper close",
            )

        filled = self._apply(symbol, Side.sell, quantity, price)
        return OrderResult(
            ok=True,
            order_id=f"paper-{next(self._ids)}",
            status="filled",
            filled_qty=filled,
            raw={"paper": True, "avg_price": price, "closing_order": True},
        )

    def get_position(self, symbol: str) -> Position | None:
        """Return the simulated position for ``symbol``, or ``None`` when flat."""
        quantity, average_cost = self._positions.get(symbol, (0.0, 0.0))
        if quantity <= _QTY_EPSILON:
            return None
        return Position(
            symbol=symbol,
            side=PositionSide.long,
            size=quantity,
            entry_price=average_cost,
        )

    def health_check(self) -> bool:
        """Return ``True``: there is no remote service to be unreachable."""
        return True

    # No contract_spec(): the supervisor already derives the spot spec from the
    # symbol when a venue does not report one, and one unit being one unit is
    # the case where that is a fact rather than a guess (#124). Declaring it
    # here would duplicate that derivation in a second place.

    def _apply(self, symbol: str, side: Side, qty: float, price: float) -> float:
        """Update the position and return the quantity actually transacted.

        Spot is long-only (#125), so a sell disposes of inventory and stops at
        zero rather than opening a short. Overselling therefore fills only the
        owned part -- inventing the rest would show the operator a trade that
        no spot venue would have accepted.
        """
        held, average_cost = self._positions.get(symbol, (0.0, 0.0))
        if side is Side.buy:
            total = held + qty
            self._positions[symbol] = (total, (held * average_cost + qty * price) / total)
            return qty

        sold = min(held, qty)
        remaining = held - sold
        if remaining <= _QTY_EPSILON:
            self._positions.pop(symbol, None)
        else:
            # Average cost is unchanged by a sale: it is the basis of what is
            # still held, and realized PnL is derived from the order log (#128).
            self._positions[symbol] = (remaining, average_cost)
        return sold
