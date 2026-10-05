"""
Run-mode plumbing of module 02_bot (Spec 1.4, INV-B9, INV-B10).

The bot is OFF by default: with ``BOT_ENABLED`` unset/false every
public entry point short-circuits before touching the database and the
game server boots normally. With the switch on but any of the four
required ``VK_*`` variables missing the mode is ``MISCONFIGURED`` — one
CRITICAL log line per process names the missing variables (never their
values) and the server still boots. ``READY`` means fully configured;
Issue 3 flips it to ``RUNNING`` once the background tasks are actually
up. ``is_bot_active()`` — the only question producers ask — is true in
``READY`` and ``RUNNING``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

logger = logging.getLogger(__name__)

MODULE_SLUG = "02_bot"

_TRUE_VALUES = frozenset({"1", "true", "yes"})

_runtime_running = False
_misconfigured_logged = False
_app_id_warned = False


class BotMode(str, Enum):
    """Lifecycle mode of the module (Spec 1.4)."""

    OFF = "OFF"
    MISCONFIGURED = "MISCONFIGURED"
    READY = "READY"
    RUNNING = "RUNNING"


@dataclass(frozen=True)
class BotEnv:
    """One snapshot of the bot environment; secrets never reach repr."""

    enabled: bool
    group_id: str | None
    group_token: str | None = field(repr=False)
    callback_secret: str | None = field(repr=False)
    callback_confirmation: str | None = field(repr=False)
    app_id: int | None


def _nonblank(value: str | None) -> str | None:
    """None for missing/whitespace-only values, else the stripped text."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def read_bot_env(environ: Mapping[str, str] = os.environ) -> BotEnv:
    """Read the bot environment at call time — nothing is cached."""
    global _app_id_warned
    raw_app_id = (environ.get("VK_APP_ID") or "").strip()
    app_id: int | None = None
    if raw_app_id:
        try:
            app_id = int(raw_app_id)
        except ValueError:
            app_id = None
    if app_id is None and not _app_id_warned:
        logger.warning(
            "VK_APP_ID is blank or not a number — the 'Создать "
            "государство' open_app button will not be shown"
        )
        _app_id_warned = True
    return BotEnv(
        enabled=(environ.get("BOT_ENABLED") or "").strip().lower()
        in _TRUE_VALUES,
        group_id=_nonblank(environ.get("VK_GROUP_ID")),
        group_token=_nonblank(environ.get("VK_GROUP_TOKEN")),
        callback_secret=_nonblank(environ.get("VK_CALLBACK_SECRET")),
        callback_confirmation=_nonblank(
            environ.get("VK_CALLBACK_CONFIRMATION")
        ),
        app_id=app_id,
    )


def get_bot_mode(env: BotEnv | None = None) -> BotMode:
    """The current mode; reads the environment fresh when env is None."""
    global _misconfigured_logged
    if env is None:
        env = read_bot_env()
    if not env.enabled:
        return BotMode.OFF
    missing = [
        name
        for name, value in (
            ("VK_GROUP_ID", env.group_id),
            ("VK_GROUP_TOKEN", env.group_token),
            ("VK_CALLBACK_SECRET", env.callback_secret),
            ("VK_CALLBACK_CONFIRMATION", env.callback_confirmation),
        )
        if value is None
    ]
    if missing:
        if not _misconfigured_logged:
            logger.critical(
                "BOT_ENABLED is on but required variables are missing: "
                "%s — the bot stays off (MISCONFIGURED)",
                ", ".join(missing),
            )
            _misconfigured_logged = True
        return BotMode.MISCONFIGURED
    if _runtime_running:
        return BotMode.RUNNING
    return BotMode.READY


def set_runtime_running(running: bool) -> None:
    """Issue 3's runtime marks READY -> RUNNING once its tasks are up."""
    global _runtime_running
    _runtime_running = running


def is_bot_active() -> bool:
    """READY or RUNNING — the gate every producer passes first."""
    return get_bot_mode() in (BotMode.READY, BotMode.RUNNING)
