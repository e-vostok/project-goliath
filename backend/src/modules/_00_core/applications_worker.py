"""
Background applications worker of module 00_core (Spec applications §6).

One task per server process, started in ``lifespan`` and stopped on
shutdown — the conscious Tick DAG exception (APP-4): review deadlines
follow wall-clock time, not game turns.

Each pass calls ``ApplicationService.run_pass``: auto-accept every
overdue PENDING application (each in its own transaction — a failed
check drops it back to DRAFT/failed, a row failure never stops the
others) and then assign a reviewer to every PENDING row still without
one. Overdue applications submitted while the server was down are
taken by the first pass after boot.

Modes: ``STOPPED`` before :meth:`ApplicationsWorker.start` and after
:meth:`ApplicationsWorker.stop`, ``RUNNING`` in between — reported to
the admin overview tile together with the moment of the last finished
pass (both live in process memory only, like the orders worker's).
Every exception except ``CancelledError`` is logged and the loop
continues — paced by consecutive-failure pauses 5, 15, 60 seconds,
reset by the first clean pass; a pass failure can never delay or fail
an API response.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.application_service import ApplicationService
from modules._00_core.config_schema import ApplicationsSettings, CoreConfig

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

# Consecutive-failure pauses of the loop (same rule as 04_orders):
# the first failure waits 5 s, the second 15 s, the third and every
# later one 60 s; the first clean pass resets the count.
FAILURE_PAUSES_SECONDS = (5.0, 15.0, 60.0)


class WorkerMode(StrEnum):
    """Lifecycle mode of the applications worker (Spec §6)."""

    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


_mode = WorkerMode.STOPPED
_last_pass_at: datetime | None = None


def get_worker_mode() -> WorkerMode:
    """The worker mode for the admin overview tile (Spec §6)."""
    return _mode


def get_last_pass_at() -> datetime | None:
    """Moment of the last finished pass, in memory (Spec §6)."""
    return _last_pass_at


class ApplicationsWorker:
    """Owns the applications auto-accept/assignment task for one app
    lifespan."""

    def __init__(
        self,
        settings: ApplicationsSettings,
        session_factory: SessionFactory,
    ):
        self._settings = settings
        self._session_factory = session_factory
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Mark RUNNING and spawn the loop."""
        global _mode
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._loop(), name="applications-worker"
        )
        _mode = WorkerMode.RUNNING

    async def stop(self) -> None:
        """Cancel and await the loop, mark STOPPED."""
        global _mode
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        _mode = WorkerMode.STOPPED

    async def _loop(self) -> None:
        """
        The long-running loop (Spec §6): run a pass, then sleep
        ``worker_interval_seconds``. Every exception except
        ``CancelledError`` is logged and the loop goes on — paced by
        ``FAILURE_PAUSES_SECONDS`` over consecutive failures, reset by
        the first clean pass.
        """
        global _last_pass_at
        interval_seconds = self._settings.worker_interval_seconds
        failures = 0
        while True:
            try:
                config = CoreConfig.from_yaml(
                    CoreConfig.get_default_config_path()
                )
                await ApplicationService.run_pass(
                    self._session_factory, config
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                pause = FAILURE_PAUSES_SECONDS[
                    min(failures, len(FAILURE_PAUSES_SECONDS) - 1)
                ]
                failures += 1
                logger.exception(
                    "00_core applications pass failed; retrying in %.0fs",
                    pause,
                )
                await asyncio.sleep(pause)
                continue
            failures = 0
            _last_pass_at = datetime.now(UTC)
            await asyncio.sleep(interval_seconds)


async def start_applications_worker_if_ready(
    session_factory: SessionFactory,
) -> ApplicationsWorker:
    """
    Spec §6 wiring: called in ``lifespan``. The worker needs no
    external service or token — it only opens its own DB transactions
    — so it always starts; ``stop()`` on shutdown turns the mode back
    to STOPPED.
    """
    settings = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    ).applications
    worker = ApplicationsWorker(settings, session_factory)
    await worker.start()
    return worker
