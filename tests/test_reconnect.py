"""Tests for the reconnect/backoff logic."""

import asyncio

import pytest

from tradingbot.stream import (
    StreamingNotSupported,
    run_async_with_reconnect,
    run_with_reconnect,
)


def test_backoff_schedule_1_2_4_capped_at_60():
    """Verify the exponential backoff schedule caps at 60 seconds."""
    sleeps = []

    def connect():
        raise ConnectionError("down")

    def should_stop():
        return len(sleeps) >= 8

    run_with_reconnect(
        connect_and_run=connect,
        should_stop=should_stop,
        sleep=sleeps.append,
    )
    assert sleeps == [1, 2, 4, 8, 16, 32, 60, 60]


def test_backoff_resets_after_healthy_connection():
    """Verify that backoff resets after a successful connection."""
    sleeps = []
    state = {"n": 0}

    def connect():
        state["n"] += 1
        if state["n"] == 1:
            return  # healthy connection that then drops
        raise ConnectionError("down")

    def should_stop():
        return len(sleeps) >= 3

    run_with_reconnect(
        connect_and_run=connect,
        should_stop=should_stop,
        sleep=sleeps.append,
    )
    assert sleeps == [1, 1, 2]


def test_stops_immediately_when_should_stop_true():
    """Verify that the reconnect loop stops immediately when should_stop is true."""
    ran = []
    sleeps = []

    run_with_reconnect(
        connect_and_run=lambda: ran.append(1),
        should_stop=lambda: True,
        sleep=sleeps.append,
    )
    assert ran == []
    assert sleeps == []


def test_gap_fill_called_after_disconnect():
    """Verify that gap_fill is invoked after a disconnect."""
    sleeps = []
    gaps = []

    def should_stop():
        return len(sleeps) >= 2

    run_with_reconnect(
        connect_and_run=lambda: None,
        should_stop=should_stop,
        gap_fill=lambda: gaps.append(1),
        sleep=sleeps.append,
    )
    assert len(gaps) >= 1


# --- async reconnect supervision (#117) -------------------------------------
#
# The service path awaits ``StreamingFeed.run_async`` on the event loop, so the
# blocking ``run_with_reconnect`` above cannot supervise it. These cover the
# async twin, which is what actually keeps a Coinbase bot alive overnight.


@pytest.mark.asyncio
async def test_async_reconnects_after_a_clean_return() -> None:
    """A stream that returns without raising is a disconnect, not a success.

    This is the exact Coinbase shape: ``run_async`` opens one socket, consumes
    until it closes, and returns cleanly. Treating that as "done" is what left
    bots on NO DATA within minutes.
    """
    connects = 0

    async def connect_and_run() -> None:
        nonlocal connects
        connects += 1

    async def sleep(_seconds: float) -> None:
        return None

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: connects >= 3,
        sleep=sleep,
    )
    assert connects == 3


@pytest.mark.asyncio
async def test_async_reconnects_after_an_exception() -> None:
    """A socket that raises is retried rather than ending the stream."""
    connects = 0

    async def connect_and_run() -> None:
        nonlocal connects
        connects += 1
        raise ConnectionResetError("socket died")

    async def sleep(_seconds: float) -> None:
        return None

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: connects >= 3,
        sleep=sleep,
    )
    assert connects == 3


@pytest.mark.asyncio
async def test_async_backoff_schedule_1_2_4_capped_at_60() -> None:
    """Repeated connect failures back off exponentially and cap at 60s."""
    sleeps: list[float] = []

    async def connect_and_run() -> None:
        raise ConnectionError("down")

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: len(sleeps) >= 8,
        sleep=sleep,
    )
    assert sleeps == [1, 2, 4, 8, 16, 32, 60, 60]


@pytest.mark.asyncio
async def test_async_backoff_resets_after_a_healthy_connection() -> None:
    """A connection that lived resets an *already grown* backoff.

    The reset only has an observable effect once the delay has climbed away
    from the base, so the schedule below fails twice before connecting. A
    version that never reset would sleep 4s after the healthy connection and
    keep climbing, leaving a bot minutes behind the market after one bad patch.
    """
    sleeps: list[float] = []
    attempts = 0

    async def connect_and_run() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 3:
            return  # connected, then dropped
        raise ConnectionError("down")

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: len(sleeps) >= 4,
        sleep=sleep,
    )
    assert sleeps == [1, 2, 1, 1]


@pytest.mark.asyncio
async def test_async_does_not_reconnect_when_stopped_during_the_backoff() -> None:
    """A stop arriving mid-backoff is honoured, not overtaken by a reconnect.

    Stopping a bot cancels its subscription; reconnecting after that would
    reopen a socket nobody is listening to and, with gap-fill, refetch history
    for a bot that is already gone.
    """
    connects = 0
    gap_fills = 0
    stopped = False

    async def connect_and_run() -> None:
        nonlocal connects
        connects += 1

    async def gap_fill() -> None:
        nonlocal gap_fills
        gap_fills += 1

    async def sleep(_seconds: float) -> None:
        nonlocal stopped
        stopped = True  # the operator stops the bot while we are backing off

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: stopped,
        gap_fill=gap_fill,
        sleep=sleep,
    )
    assert connects == 1
    assert gap_fills == 0


@pytest.mark.asyncio
async def test_async_stops_immediately_when_should_stop_is_true() -> None:
    """Nothing connects and nothing sleeps once the caller has stopped."""
    ran: list[int] = []
    sleeps: list[float] = []

    async def connect_and_run() -> None:
        ran.append(1)

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: True,
        sleep=sleep,
    )
    assert ran == []
    assert sleeps == []


@pytest.mark.asyncio
async def test_async_gap_fill_runs_before_reconnecting() -> None:
    """Bars missed during the outage are REST-filled before the socket reopens.

    Order matters: filling after the reconnect would race the first live bar
    and could hand the strategy an out-of-order buffer.
    """
    order: list[str] = []

    async def connect_and_run() -> None:
        order.append("connect")

    async def gap_fill() -> None:
        order.append("gap_fill")

    async def sleep(_seconds: float) -> None:
        return None

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: order.count("connect") >= 2,
        gap_fill=gap_fill,
        sleep=sleep,
    )
    assert order == ["connect", "gap_fill", "connect"]


@pytest.mark.asyncio
async def test_async_reports_every_drop_to_on_drop() -> None:
    """Each disconnect is reported, with the exception when there was one."""
    drops: list[BaseException | None] = []
    attempts = 0
    failure = ConnectionError("down")

    async def connect_and_run() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return
        raise failure

    async def sleep(_seconds: float) -> None:
        return None

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: attempts >= 2,
        on_drop=drops.append,
        sleep=sleep,
    )
    assert drops == [None, failure]


@pytest.mark.asyncio
async def test_async_fatal_exception_propagates_without_retrying() -> None:
    """A venue that cannot stream at all must not be retried forever.

    ``StreamingNotSupported`` fails identically on every attempt, so backing
    off against it would burn the loop and hide the real cause from the
    operator (#170).
    """
    attempts = 0
    sleeps: list[float] = []

    async def connect_and_run() -> None:
        nonlocal attempts
        attempts += 1
        raise StreamingNotSupported("no watchOHLCV")

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    # Bounded so that a supervisor which *did* retry ends the test by failing
    # the assertion below, rather than by spinning forever.
    with pytest.raises(StreamingNotSupported):
        await run_async_with_reconnect(
            connect_and_run=connect_and_run,
            should_stop=lambda: attempts >= 5,
            fatal=lambda exc: isinstance(exc, StreamingNotSupported),
            sleep=sleep,
        )
    assert attempts == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_async_cancellation_is_not_treated_as_a_drop() -> None:
    """Cancelling the supervising task must actually stop it.

    The hub unsubscribes by cancelling. If cancellation were caught and
    retried like a dropped socket, a stopped bot would keep its stream open
    forever and the task could never be awaited to completion.
    """
    connects = 0

    async def connect_and_run() -> None:
        nonlocal connects
        connects += 1
        await asyncio.sleep(3600)

    task = asyncio.create_task(
        run_async_with_reconnect(
            connect_and_run=connect_and_run,
            should_stop=lambda: False,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    # Bounded: a supervisor that swallowed the cancellation would reconnect and
    # never finish, so without the timeout this test would hang rather than fail.
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert connects == 1


@pytest.mark.asyncio
async def test_async_does_not_sleep_after_the_final_drop() -> None:
    """A stream stopped while disconnected exits at once, not after a backoff.

    Without the stop check between the drop and the sleep, a bot stopped
    during an outage would sit in a backoff of up to 60s before its task could
    finish, stalling shutdown for no reason.
    """
    sleeps: list[float] = []
    stopped = False

    async def connect_and_run() -> None:
        nonlocal stopped
        stopped = True

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    await run_async_with_reconnect(
        connect_and_run=connect_and_run,
        should_stop=lambda: stopped,
        sleep=sleep,
    )
    assert sleeps == []
