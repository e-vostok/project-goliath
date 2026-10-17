"""
Background VK profile worker of module 03_registry (Spec 2.3, 2.4).

Modes: ``OFF`` (``profiles.enabled = false``), ``NO_TOKEN`` (enabled
but ``VK_GROUP_TOKEN`` blank — one WARNING per process), ``RUNNING``.
The token is read by this module from the environment and never
logged. The long-running loop wraps ``run_cycle`` and wakes every
``profiles.wake_interval_minutes`` or when the module-level
``asyncio.Event`` is set by the players-table source (a player without
a profile row, or a row with a due ``next_attempt_at``). INV-R6: the
loop catches every exception except ``CancelledError``, logs it and
keeps going — a VK failure can never delay or fail an API response or
the tick.

``run_cycle`` is the testable core (Spec 2.4 steps 1–4): create
missing ``PENDING`` rows for players seen through
``PlayerService.list_for_registry`` (the module never reads
``players`` directly), take up to ``batch_size`` due rows (oldest
``next_attempt_at`` first), one ``users.get`` per batch, apply the
Spec 2.3 FSM in ONE transaction per batch, then pause
``batch_pause_seconds`` while due rows remain.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, suppress
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import PlayerService
from modules._03_registry.config_schema import ProfilesConfig
from modules._03_registry.models import RegistryVkProfile
from modules._03_registry.vk_profiles import (
    BatchFailure,
    BatchResult,
    OutcomeKind,
    VkProfilesClient,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class WorkerMode(str, Enum):
    """Lifecycle mode of the profile worker (Spec 2.4)."""

    OFF = "OFF"
    NO_TOKEN = "NO_TOKEN"
    RUNNING = "RUNNING"


_mode = WorkerMode.OFF
_last_cycle_at: datetime | None = None
_wake_event: asyncio.Event | None = None
_no_token_warned = False
_invalid_token_logged = False


def get_worker_mode() -> WorkerMode:
    """The worker mode as decided at start (Spec 5.4)."""
    return _mode


def get_last_cycle_at() -> datetime | None:
    """Moment of the last finished cycle, in memory (Spec 5.4)."""
    return _last_cycle_at


def install_wake_event(event: asyncio.Event | None) -> None:
    """Install the worker's bell, or clear it on shutdown."""
    global _wake_event
    _wake_event = event


def request_wake() -> None:
    """Ring the bell if one is installed; a no-op otherwise."""
    event = _wake_event
    if event is not None:
        event.set()


def aware_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def read_vk_group_token(environ: Mapping[str, str] = os.environ) -> str | None:
    """The community key; ``None`` when missing or blank. Never logged."""
    raw = environ.get("VK_GROUP_TOKEN")
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


async def run_cycle(
    session_factory: SessionFactory,
    client: VkProfilesClient,
    profiles: ProfilesConfig,
    now: datetime,
) -> None:
    """
    One wake pass of Spec 2.4.

    Per batch two transactions on one session: create missing
    ``PENDING`` rows + select the due batch, then — after the VK call,
    which never runs inside a transaction — apply the outcome in one
    transaction. The batch's ORM rows stay attached to the session
    across both transactions, so the apply step needs no re-read.
    """
    while True:
        async with session_factory() as session:
            async with session.begin():
                players = await PlayerService.list_for_registry(session)
                vk_by_player = {row.player_id: row.vk_user_id for row in players}
                existing = set(
                    (await session.execute(select(RegistryVkProfile.player_id)))
                    .scalars()
                    .all()
                )
                for player in players:
                    if player.player_id not in existing:
                        session.add(
                            RegistryVkProfile(
                                player_id=player.player_id,
                                status="PENDING",
                                next_attempt_at=now,
                            )
                        )
                await session.flush()
                due = (
                    (
                        await session.execute(
                            select(RegistryVkProfile)
                            .where(RegistryVkProfile.next_attempt_at <= now)
                            .order_by(RegistryVkProfile.next_attempt_at)
                            .limit(profiles.batch_size + 1)
                        )
                    )
                    .scalars()
                    .all()
                )
                batch = due[: profiles.batch_size]
                more = len(due) > profiles.batch_size

            if not batch:
                return

            reply = await client.get_profiles(
                [vk_by_player[row.player_id] for row in batch]
            )

            async with session.begin():
                _apply_batch(batch, vk_by_player, reply, profiles, now)

        if not more:
            return
        if profiles.batch_pause_seconds:
            await asyncio.sleep(profiles.batch_pause_seconds)


def _apply_batch(
    batch: list[RegistryVkProfile],
    vk_by_player: dict[str, int],
    reply: BatchResult,
    profiles: ProfilesConfig,
    now: datetime,
) -> None:
    """
    The Spec 2.3 FSM inside the caller's transaction.

    A batch-level failure (invalid key, transport, any other error)
    changes only ``next_attempt_at = now + failure_retry_minutes`` —
    status, names, photo and ``fetched_at`` stay. Per-player answers
    set ``fetched_at = now`` and ``next_attempt_at = now + ttl_hours``;
    ``OK`` stores the cleaned values, ``UNAVAILABLE`` keeps the last
    successful name and photo.
    """
    global _invalid_token_logged
    if reply.failure is not None:
        if reply.failure is BatchFailure.INVALID_TOKEN:
            if not _invalid_token_logged:
                logger.critical(
                    "vk users.get rejected the access key (error %s) — "
                    "check VK_GROUP_TOKEN; the worker retries every "
                    "failure_retry_minutes",
                    reply.error_code,
                )
                _invalid_token_logged = True
        else:
            logger.warning(
                "vk users.get batch failed (error %s) — rows unchanged, "
                "retry after failure_retry_minutes",
                reply.error_code,
            )
        retry_at = now + timedelta(minutes=profiles.failure_retry_minutes)
        for row in batch:
            row.next_attempt_at = retry_at
        return

    next_at = now + timedelta(hours=profiles.ttl_hours)
    for row in batch:
        outcome = reply.outcomes.get(vk_by_player[row.player_id])
        if outcome is not None and outcome.kind is OutcomeKind.OK:
            row.status = "OK"
            row.first_name = outcome.first_name
            row.last_name = outcome.last_name
            row.photo_url = outcome.photo_url
        else:
            row.status = "UNAVAILABLE"
        row.fetched_at = now
        row.next_attempt_at = next_at


class ProfileWorker:
    """Owns the profiles background task for one app lifespan."""

    def __init__(
        self,
        profiles: ProfilesConfig,
        token: str,
        session_factory: SessionFactory,
        transport=None,
    ):
        self._profiles = profiles
        self._session_factory = session_factory
        self._wake = asyncio.Event()
        self._client = VkProfilesClient(profiles, token, transport=transport)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Install the bell, mark RUNNING and spawn the loop."""
        global _mode
        if self._task is not None:
            return
        install_wake_event(self._wake)
        self._task = asyncio.create_task(self._loop(), name="registry-profiles")
        _mode = WorkerMode.RUNNING

    async def stop(self) -> None:
        """Cancel and await the loop, clear the bell, close the client."""
        global _mode
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        install_wake_event(None)
        _mode = WorkerMode.OFF
        await self._client.aclose()

    async def _loop(self) -> None:
        """
        The long-running loop (Spec 2.4): run a cycle, then wait for the
        bell or ``wake_interval_minutes``. INV-R6 — every exception
        except ``CancelledError`` is logged and the loop continues.
        """
        global _last_cycle_at
        interval_seconds = self._profiles.wake_interval_minutes * 60
        while True:
            try:
                await run_cycle(
                    self._session_factory,
                    self._client,
                    self._profiles,
                    datetime.now(timezone.utc),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("03_registry profile cycle failed")
            else:
                _last_cycle_at = datetime.now(timezone.utc)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()


async def start_profile_worker_if_ready(
    session_factory: SessionFactory,
    transport=None,
) -> ProfileWorker | None:
    """
    Spec 2.4 wiring: ``OFF``/``NO_TOKEN`` start nothing and never
    affect the boot; ``RUNNING`` gets a ProfileWorker whose loop is up.
    ``NO_TOKEN`` (enabled, but ``VK_GROUP_TOKEN`` blank) logs one
    WARNING per process — the value itself is never logged.
    """
    global _mode, _no_token_warned
    # Local import: the config holder lives in startup.py, which
    # sources.py imports — a top-level import would be a cycle.
    from modules._03_registry.startup import get_registry_config

    profiles = get_registry_config().profiles
    if not profiles.enabled:
        _mode = WorkerMode.OFF
        return None
    token = read_vk_group_token()
    if token is None:
        _mode = WorkerMode.NO_TOKEN
        if not _no_token_warned:
            logger.warning(
                "03_registry: VK_GROUP_TOKEN is blank — VK profiles "
                "stay off (NO_TOKEN); tables show fallback names"
            )
            _no_token_warned = True
        return None
    worker = ProfileWorker(profiles, token, session_factory, transport=transport)
    await worker.start()
    return worker
