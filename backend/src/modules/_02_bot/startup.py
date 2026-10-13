"""
Startup wiring of module 02_bot (Spec 2.5, steps 1–2 — Issues 2–4).

``startup_bot()`` runs from the app lifespan right after
``startup_map()`` — synchronous (no database, no network, no
background tasks; those arrive with Issue 3) and idempotent:

1. load and validate ``configs/02_bot.yaml`` — always, even with
   ``BOT_ENABLED=false``: a broken YAML must stop the server;
2. register the builtin notification types and check the registry
   against the config (``BotRegistryError`` aborts the boot);
3. register the admin hooks (state view + world reset);
4. log the mode — names of missing variables only, never values.

The validated config is kept in a module-level holder for
``get_bot_config()`` so the queue code never re-reads the YAML.
"""

from __future__ import annotations

import logging

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.hooks import (
    STAGE_BEFORE_ALL,
    register_nation_created_hook,
    register_registration_check,
)
from modules._02_bot.admin_hooks import register_bot_admin_hooks
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.nation_hook import nation_created_hook
from modules._02_bot.registration_check import check_registration_consent
from modules._02_bot.registry import (
    register_builtin_types,
    validate_registry_against_config,
)
from modules._02_bot.settings import (
    MODULE_SLUG,
    BotMode,
    get_bot_mode,
    read_bot_env,
)

logger = logging.getLogger(__name__)

_bot_config: BotConfig | None = None


def get_bot_config() -> BotConfig:
    """The config loaded by :func:`startup_bot`; raises before it ran."""
    if _bot_config is None:
        raise RuntimeError(
            "BotConfig is not loaded — startup_bot() has not run"
        )
    return _bot_config


def startup_bot() -> BotConfig:
    """Boot the module's static parts; returns the validated config."""
    global _bot_config
    config = BotConfig.from_yaml(BotConfig.get_default_config_path())
    register_builtin_types()
    validate_registry_against_config(config)
    register_bot_admin_hooks()
    # Spec 3.10: the consent gate on nation registration — always
    # registered; the check itself gates on the bot mode and on
    # consent.required_for_registration, so an OFF bot never sees it.
    register_registration_check(
        STAGE_BEFORE_ALL,
        f"{MODULE_SLUG}.consent",
        check_registration_consent,
    )
    # Spec 3.11: the «nation created» message — always registered; the
    # hook itself gates on the bot mode and the stored consent, so an
    # OFF bot queues nothing.
    register_nation_created_hook(
        f"{MODULE_SLUG}.nation_created",
        nation_created_hook,
    )
    _bot_config = config
    logger.info("02_bot started: mode=%s", get_bot_mode().value)
    return config


async def start_runtime_if_ready(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
):
    """
    Issue 3 wiring (Spec 2.5 step 3): a ``READY`` bot gets a BotRuntime
    with its four tasks; ``OFF``/``MISCONFIGURED`` (and an already
    ``RUNNING`` second lifespan) start nothing. Returns the runtime or
    None — the caller stops it on shutdown.
    """
    from modules._02_bot.runtime import BotRuntime

    env = read_bot_env()
    if get_bot_mode(env) is not BotMode.READY:
        return None
    runtime = BotRuntime(get_bot_config(), env, session_factory)
    await runtime.start()
    return runtime
