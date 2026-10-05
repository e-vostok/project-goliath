"""
BotRuntime of module 02_bot (Spec 2.5) — the four background tasks.

``start()`` installs the wake bell (Spec 3.1), builds the VK client,
limiter, breaker and sender, then spawns:

- ``sender`` — waits for the bell or ``poll_interval_seconds``, then
  claims a batch and sends it (Spec 3.2/3.3);
- ``digest_watcher`` — every ``poll_interval_seconds`` (Spec 3.8);
- ``consent_reconciler`` — every ``reconcile_sweep_interval_seconds``
  (Spec 3.7);
- ``janitor`` — hourly (Spec 2.5).

Every task body is wrapped in the supervision loop: a step runs, an
``Exception`` is logged and paced with a 5 s -> 60 s backoff, and the
task continues — one failure never kills it; ``CancelledError``
propagates. Each task stamps its last successful pass for the admin
view (INV-B13). ``stop()`` cancels and awaits the tasks, returns this
process's LEASED rows to PENDING (best effort), closes the VK client
and clears the bell. ``set_runtime_running`` tracks start/stop so
``get_bot_mode`` reports READY -> RUNNING.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from modules._02_bot.breaker import CircuitBreaker
from modules._02_bot.claim import claim_batch
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.janitor import janitor_step
from modules._02_bot.limiter import TokenBucket
from modules._02_bot.models import BotOutbox
from modules._02_bot.reconciler import reconcile_step
from modules._02_bot.sender import Sender
from modules._02_bot.settings import (
    BotEnv,
    set_active_runtime,
    set_runtime_running,
)
from modules._02_bot.signal import install_wake_event
from modules._02_bot.vk_client import VkClient
from modules._02_bot.watcher import digest_watcher_step

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

TASK_NAMES = ("sender", "digest_watcher", "consent_reconciler", "janitor")


class BotRuntime:
    """Owns the module's background tasks for one app lifespan."""

    def __init__(
        self,
        config: BotConfig,
        env: BotEnv,
        session_factory: SessionFactory,
        transport=None,
    ):
        self._config = config
        self._env = env
        self._session_factory = session_factory
        self._wake = asyncio.Event()
        self._vk = VkClient(
            config, env.group_token or "", env.group_id or "0",
            transport=transport,
        )
        self._limiter = TokenBucket(config.sender.max_requests_per_second)
        self._breaker = CircuitBreaker(config.breaker)
        self._sender = Sender(
            config,
            env,
            session_factory,
            self._vk,
            self._limiter,
            self._breaker,
        )
        self._tasks: dict[str, asyncio.Task] = {}
        self._last_pass: dict[str, datetime | None] = {
            name: None for name in TASK_NAMES
        }
        self._started = False

    async def start(self) -> None:
        """Install the bell and spawn the four supervised tasks."""
        if self._started:
            return
        install_wake_event(self._wake)
        sender = self._config.sender
        self._tasks = {
            "sender": self._spawn(
                "sender",
                lambda: self._periodic(
                    "sender", 0, self._sender_step
                ),
            ),
            "digest_watcher": self._spawn(
                "digest_watcher",
                lambda: self._periodic(
                    "digest_watcher",
                    sender.poll_interval_seconds,
                    self._watcher_step,
                ),
            ),
            "consent_reconciler": self._spawn(
                "consent_reconciler",
                lambda: self._periodic(
                    "consent_reconciler",
                    self._config.consent.reconcile_sweep_interval_seconds,
                    self._reconcile_step,
                ),
            ),
            "janitor": self._spawn(
                "janitor",
                lambda: self._periodic("janitor", 3600, self._janitor_step),
            ),
        }
        self._started = True
        set_active_runtime(self)
        set_runtime_running(True)

    async def stop(self) -> None:
        """Cancel, await, return LEASED rows, close the client."""
        if not self._started:
            return
        self._started = False
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        # Best effort: a clean stop frees rows this process leased;
        # a crash leaves them to lease expiry (Spec 2.5 step 4).
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    # Single-process deployment: every LEASED row is
                    # this process's. Returning them early loses
                    # nothing — the lease would only guard sends that
                    # are now cancelled anyway.
                    await session.execute(
                        update(BotOutbox)
                        .where(BotOutbox.status == "LEASED")
                        .values(
                            status="PENDING",
                            lease_until=None,
                            lease_token=None,
                        )
                    )
        except Exception:
            logger.exception("bot runtime: returning LEASED rows failed")
        await self._vk.aclose()
        install_wake_event(None)
        set_active_runtime(None)
        set_runtime_running(False)

    def _spawn(self, name: str, body) -> asyncio.Task:
        return asyncio.create_task(body(), name=f"bot-{name}")

    async def _periodic(
        self, name: str, interval_seconds: float, step
    ) -> None:
        """
        The supervision loop (Spec 2.5): step -> stamp the pass ->
        sleep; on Exception log, pace 5 s -> 60 s and continue;
        CancelledError propagates.
        """
        backoff = 5.0
        while True:
            try:
                await step()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "bot task '%s' failed; retrying in %.0fs",
                    name,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            self._last_pass[name] = datetime.now(timezone.utc)
            backoff = 5.0
            await asyncio.sleep(interval_seconds)

    async def _sender_step(self) -> None:
        """Wait for the bell or the poll timeout, then claim + send."""
        try:
            await asyncio.wait_for(
                self._wake.wait(),
                timeout=self._config.sender.poll_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass
        self._wake.clear()
        async with self._session_factory() as session:
            groups = await claim_batch(
                session,
                self._config,
                self._env,
                datetime.now(timezone.utc),
            )
            await session.commit()
        await self._sender.process_groups(groups)

    async def _watcher_step(self) -> None:
        await digest_watcher_step(self._session_factory, self._config)

    async def _reconcile_step(self) -> None:
        await reconcile_step(
            self._session_factory,
            self._config,
            self._env,
            self._vk,
            self._limiter,
        )

    async def _janitor_step(self) -> None:
        await janitor_step(self._session_factory, self._config)

    # -- admin view (Spec 5.4) -------------------------------------------------

    def sender_state(self) -> str:
        """RUNNING / BREAKER_OPEN / HALF_OPEN / HALTED_AUTH."""
        return self._sender.status_word()

    def task_last_pass(self) -> dict[str, str | None]:
        """Task name -> ISO time of its last successful pass, or None."""
        return {
            name: stamp.isoformat() if stamp is not None else None
            for name, stamp in self._last_pass.items()
        }
