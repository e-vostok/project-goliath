"""
Background retry worker of module 04_orders (Spec 2.3, 2.4).

One task per server process, started in ``lifespan`` after
``startup_orders()`` and stopped on shutdown — the conscious Tick DAG
exception (Spec 2.4, D3): distribution retries and judge reminders
follow wall-clock time, not game turns.

Modes: ``STOPPED`` before :meth:`OrdersWorker.start` and after
:meth:`OrdersWorker.stop`, ``RUNNING`` in between — reported to the
admin state view together with the moment of the last finished pass
(both live in process memory only, like the profile worker's).

The loop runs ``OrderService.run_retry_pass``, then waits for the
module-level ``asyncio.Event`` bell or
``distribution.retry_interval_seconds``. The router rings the bell via
:func:`request_orders_wake` after a committed submission (a new order
may be waiting for a judge) and after a committed verdict (a freed
load slot may unblock a waiting order); without a running worker the
call is a no-op. Every exception except ``CancelledError`` is logged
and the loop continues — a pass failure can never delay or fail an API
response; consecutive failures pace the next attempts 5, 15, 60
seconds, and the first clean pass resets the pause.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from modules._04_orders.config_schema import DistributionSettings
from modules._04_orders.service import OrderService

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# Consecutive-failure pauses of the loop (Spec 2.3): the first failure
# waits 5 s, the second 15 s, the third and every later one 60 s; the
# first clean pass resets the count. Module-level so tests can shrink
# it without touching the loop.
FAILURE_PAUSES_SECONDS = (5.0, 15.0, 60.0)


class WorkerMode(str, Enum):
    """Lifecycle mode of the orders worker (Spec 5.7)."""

    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


_mode = WorkerMode.STOPPED
_last_pass_at: datetime | None = None
_wake_event: asyncio.Event | None = None


def get_worker_mode() -> WorkerMode:
    """The worker mode for the admin state view (Spec 5.7)."""
    return _mode


def get_last_pass_at() -> datetime | None:
    """Moment of the last finished pass, in memory (Spec 5.7)."""
    return _last_pass_at


def install_wake_event(event: asyncio.Event | None) -> None:
    """Install the worker's bell, or clear it on shutdown."""
    global _wake_event
    _wake_event = event


def request_orders_wake() -> None:
    """Ring the bell if one is installed; a no-op otherwise."""
    event = _wake_event
    if event is not None:
        event.set()


class OrdersWorker:
    """Owns the orders retry/reminder task for one app lifespan."""

    def __init__(
        self,
        distribution: DistributionSettings,
        session_factory: SessionFactory,
    ):
        self._distribution = distribution
        self._session_factory = session_factory
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Install the bell, mark RUNNING and spawn the loop."""
        global _mode
        if self._task is not None:
            return
        install_wake_event(self._wake)
        self._task = asyncio.create_task(
            self._loop(), name="orders-retry"
        )
        _mode = WorkerMode.RUNNING

    async def stop(self) -> None:
        """Cancel and await the loop, clear the bell, mark STOPPED."""
        global _mode
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        install_wake_event(None)
        _mode = WorkerMode.STOPPED

    async def _loop(self) -> None:
        """
        The long-running loop (Spec 2.3): run a pass, then wait for the
        bell or ``retry_interval_seconds``. Every exception except
        ``CancelledError`` is logged and the loop goes on — paced by
        ``FAILURE_PAUSES_SECONDS`` over consecutive failures, reset by
        the first clean pass.
        """
        global _last_pass_at
        interval_seconds = self._distribution.retry_interval_seconds
        failures = 0
        while True:
            try:
                await OrderService.run_retry_pass(self._session_factory)
            except asyncio.CancelledError:
                raise
            except Exception:
                pause = FAILURE_PAUSES_SECONDS[
                    min(failures, len(FAILURE_PAUSES_SECONDS) - 1)
                ]
                failures += 1
                logger.exception(
                    "04_orders retry pass failed; retrying in %.0fs",
                    pause,
                )
                await asyncio.sleep(pause)
                continue
            failures = 0
            _last_pass_at = datetime.now(timezone.utc)
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=interval_seconds
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()


async def start_orders_worker_if_ready(
    session_factory: SessionFactory,
) -> OrdersWorker:
    """
    Spec 2.3 wiring: called in ``lifespan`` after ``startup_orders()``.
    The worker needs no external service or token — it only opens its
    own DB transactions and enqueues bot rows — so it always starts;
    ``stop()`` on shutdown turns the mode back to STOPPED.
    """
    # Local import: the config holder lives in startup.py — a top-level
    # import would cycle (startup -> admin_hooks -> worker).
    from modules._04_orders.startup import get_orders_config

    worker = OrdersWorker(
        get_orders_config().distribution, session_factory
    )
    await worker.start()
    return worker
