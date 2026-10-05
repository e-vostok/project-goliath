"""
Startup wiring of module 02_bot (Spec 2.5, steps 1–2 — Issue 2).

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

from modules._02_bot.admin_hooks import register_bot_admin_hooks
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.registry import (
    register_builtin_types,
    validate_registry_against_config,
)
from modules._02_bot.settings import get_bot_mode

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
    _bot_config = config
    logger.info("02_bot started: mode=%s", get_bot_mode().value)
    return config
