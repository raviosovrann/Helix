"""Strategy registry and ``@strategy`` decorator."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from .base import DataRequirements, Strategy, StrategyContext

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..venues.capabilities import StrategyRequirements

_Factory = Callable[[StrategyContext], Strategy]
_factories: dict[str, _Factory] = {}
_candidates: dict[str, Any] = {}
"""The registered class/factory itself, so its declared requirements can be read."""


def strategy(name: str) -> Callable[[Any], Any]:
    """Register a strategy class or factory under ``name``.

    Args:
        name: Public name used to reference the strategy in bot configs.

    Returns:
        A decorator that registers the candidate and returns it unchanged.

    Raises:
        ValueError: If ``name`` is empty or already registered.
        TypeError: If the candidate is not callable and has no ``create`` method.
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("strategy name must not be empty")

    def decorator(candidate: Any) -> Any:
        """Register ``candidate`` and return it for use in module scope."""
        if not callable(candidate) and not callable(getattr(candidate, "create", None)):
            raise TypeError("strategy candidate must be callable or expose callable create(ctx)")
        if normalized_name in _factories:
            raise ValueError(f"strategy {normalized_name!r} is already registered")

        def factory(ctx: StrategyContext) -> Strategy:
            """Build the strategy instance using the registered candidate."""
            create = getattr(candidate, "create", None)
            if callable(create):
                return cast(Strategy, create(ctx))
            return cast(Strategy, candidate(ctx))

        _factories[normalized_name] = factory
        _candidates[normalized_name] = candidate
        return candidate

    return decorator


def build_strategy(name: str, ctx: StrategyContext) -> Strategy:
    """Instantiate the strategy registered under ``name``.

    Args:
        name: Registered strategy name.
        ctx: Runtime context passed to the strategy factory.

    Returns:
        A strategy instance implementing the ``Strategy`` protocol.

    Raises:
        ValueError: If ``name`` is empty or not registered.
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("strategy name must not be empty")
    try:
        factory = _factories[normalized_name]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {normalized_name}") from exc
    return factory(ctx)


def strategy_requirements(name: str) -> "StrategyRequirements":
    """Return what the strategy registered under ``name`` needs from a venue.

    Requirements are opt-in: a strategy that declares nothing gets the empty
    default and stays valid on every venue. Demanding a declaration would bar
    every existing strategy from spot for no reason (#125).

    Args:
        name: Registered strategy name.

    Returns:
        The strategy's declared requirements, or the empty default.
    """
    from ..venues.capabilities import StrategyRequirements

    candidate = _candidates.get(name.strip())
    declared = getattr(candidate, "requirements", None)
    if isinstance(declared, StrategyRequirements):
        return declared
    return StrategyRequirements()


def strategy_data_requirements(name: str) -> DataRequirements:
    """Return the history the strategy registered under ``name`` needs (#130).

    Opt-in like ``strategy_requirements``: a strategy reading only the candles
    handed to ``on_bar`` declares nothing and gets the empty default, so no
    existing strategy has to change.

    Args:
        name: Registered strategy name.

    Returns:
        The strategy's declared history requirements, or the empty default.
    """
    candidate = _candidates.get(name.strip())
    declared = getattr(candidate, "data_requirements", None)
    if isinstance(declared, DataRequirements):
        return declared
    return DataRequirements()


def is_demo_strategy(name: str) -> bool:
    """Return whether the strategy registered under ``name`` is demo-only (#119).

    A demo strategy exists so the plumbing can be watched end to end; it has no
    risk management and no reason to be pointed at money. The marker lives on
    the class rather than on a name check so renaming the strategy cannot
    quietly unblock it.

    Args:
        name: Registered strategy name.

    Returns:
        True when the strategy declares ``demo_only``.
    """
    return getattr(_candidates.get(name.strip()), "demo_only", False) is True


def available_strategies() -> list[str]:
    """Return all registered strategy names in alphabetical order."""
    return sorted(_factories)

