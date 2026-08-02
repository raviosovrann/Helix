"""The ``HELIX_*`` settings, and the ``TRADINGBOT_*`` names they replaced.

The project was renamed after operators were already running it, so every
setting has two spellings. Dropping the old one would have silently reset a
live deployment's data directory to ``data`` and made its stored credentials
unreadable — the encryption key is an environment variable, and a key that is
merely *absent* looks exactly like one that is wrong.
"""

from __future__ import annotations

import pytest

from helix.config import LEGACY_PREFIX, PREFIX, env


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove both spellings of the setting these tests use."""
    monkeypatch.delenv(f"{PREFIX}DATA_DIR", raising=False)
    monkeypatch.delenv(f"{LEGACY_PREFIX}DATA_DIR", raising=False)


def test_the_prefixes_are_the_two_names_the_project_has_had() -> None:
    """Verify the constants, since the whole fallback rests on them."""
    assert PREFIX == "HELIX_"
    assert LEGACY_PREFIX == "TRADINGBOT_"


def test_the_new_name_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the current spelling works."""
    monkeypatch.setenv("HELIX_DATA_DIR", "/srv/helix")

    assert env("DATA_DIR", "data") == "/srv/helix"


def test_the_legacy_name_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a deployment configured before the rename keeps running.

    This is the whole point of the fallback: an operator whose systemd unit
    still says ``TRADINGBOT_SECRETS_KEY`` must not find their stored venue
    credentials undecryptable after a routine upgrade.
    """
    monkeypatch.setenv("TRADINGBOT_DATA_DIR", "/srv/old")

    assert env("DATA_DIR", "data") == "/srv/old"


def test_the_new_name_wins_when_both_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify migrating is a matter of adding the new variable.

    An operator adds ``HELIX_*`` alongside the old one, confirms the service
    is healthy, and only then removes the legacy line. That is only safe if the
    new name takes precedence.
    """
    monkeypatch.setenv("TRADINGBOT_DATA_DIR", "/srv/old")
    monkeypatch.setenv("HELIX_DATA_DIR", "/srv/helix")

    assert env("DATA_DIR", "data") == "/srv/helix"


def test_an_explicitly_empty_new_name_wins_over_the_legacy_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify presence decides, not truthiness.

    Setting a variable to empty is how an operator turns a setting off. If
    emptiness fell through to the legacy name, the old value would come back
    and the deliberate override would be ignored.
    """
    monkeypatch.setenv("TRADINGBOT_DATA_DIR", "/srv/old")
    monkeypatch.setenv("HELIX_DATA_DIR", "")

    assert env("DATA_DIR", "data") == ""


def test_the_default_is_returned_when_neither_is_set() -> None:
    """Verify an unconfigured setting falls back to its default."""
    assert env("DATA_DIR", "data") == "data"


def test_reading_a_legacy_name_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify the operator is told to migrate, without flooding the log.

    Several of these are read on every request, so warning per read would bury
    the log. The message has to name both spellings — a warning that does not
    say what to rename it to costs the reader a grep.
    """
    monkeypatch.setenv("TRADINGBOT_DATA_DIR", "/srv/old")
    from helix import config

    config.reset_deprecation_warnings()
    with caplog.at_level("WARNING"):
        env("DATA_DIR", "data")
        env("DATA_DIR", "data")
        env("DATA_DIR", "data")

    warnings = [record for record in caplog.records if "TRADINGBOT_DATA_DIR" in record.message]
    assert len(warnings) == 1
    assert "HELIX_DATA_DIR" in warnings[0].message


def test_the_new_name_does_not_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify a correctly configured deployment logs nothing."""
    monkeypatch.setenv("HELIX_DATA_DIR", "/srv/helix")
    from helix import config

    config.reset_deprecation_warnings()
    with caplog.at_level("WARNING"):
        env("DATA_DIR", "data")

    assert caplog.records == []
