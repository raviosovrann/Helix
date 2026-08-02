"""Environment settings, under both names the project has had.

Every setting is spelled ``HELIX_*``. It was ``TRADINGBOT_*`` before the
rename, and operators were already running the service by then, so the old
spelling is still honoured and warned about rather than dropped.

Dropping it would not have failed loudly. ``HELIX_DATA_DIR`` unset simply
defaults to ``data``, so a live deployment would have come back up pointing at
an empty directory with no bots in it; and ``HELIX_SECRETS_KEY`` unset makes
stored venue credentials unreadable, which is indistinguishable from the key
being wrong. Both are worse than a deprecation warning.

Read settings through :func:`env` rather than ``os.environ`` directly, so the
fallback and the warning live in one place.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

PREFIX = "HELIX_"
"""Prefix every setting is read under."""

LEGACY_PREFIX = "TRADINGBOT_"
"""Prefix used before the rename. Still honoured; warned about once each."""

_warned: set[str] = set()
"""Legacy names already warned about, so a per-request read logs once."""


def reset_deprecation_warnings() -> None:
    """Forget which legacy names have been warned about.

    For tests, which would otherwise see the warning suppressed by whatever
    ran before them.
    """
    _warned.clear()


def env(name: str, default: str = "") -> str:
    """Return setting ``name``, preferring the current spelling.

    Presence decides, not truthiness: a ``HELIX_*`` variable set to the empty
    string wins over a legacy one that has a value. Setting a variable empty is
    how an operator turns a setting off, and falling through would quietly
    reinstate the value they were overriding.

    Args:
        name: Setting name without a prefix, e.g. ``DATA_DIR``.
        default: Returned when neither spelling is present.

    Returns:
        The configured value, or ``default``.
    """
    current = PREFIX + name
    if current in os.environ:
        return os.environ[current]

    legacy = LEGACY_PREFIX + name
    if legacy in os.environ:
        if legacy not in _warned:
            _warned.add(legacy)
            _log.warning(
                "%s is deprecated and will stop being read; rename it to %s",
                legacy, current,
            )
        return os.environ[legacy]
    return default
