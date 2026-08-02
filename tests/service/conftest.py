"""Shared fixtures for service tests."""

from __future__ import annotations

import os

import pytest

from helix.config import LEGACY_PREFIX
from helix.service.crypto import generate_key

# One key for the whole test session so encrypt/decrypt round-trips consistently.
_TEST_SECRETS_KEY = generate_key()


@pytest.fixture(autouse=True)
def _no_legacy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide any pre-rename ``TRADINGBOT_*`` variables from the tests.

    Settings still fall back to the old spelling (``helix.config``), so a
    developer whose shell exports ``TRADINGBOT_SECRETS_KEY`` from before the
    rename would silently satisfy the tests that assert on a *missing* key.
    The fallback has its own tests; everything else should see only the current
    names.
    """
    for name in [key for key in os.environ if key.startswith(LEGACY_PREFIX)]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _secrets_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a secrets-encryption key for every service test."""
    monkeypatch.setenv("HELIX_SECRETS_KEY", _TEST_SECRETS_KEY)
