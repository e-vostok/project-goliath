"""
Shared fixtures for the 02_bot suite (Issues 1+2).

Everything the module keeps process-global is snapshotted and restored
by ``bot_isolation``: the notification-type/deadline registries, the
AdminRegistry hooks, the settings flags and the wake bell. ``bot_env``
provides a fully configured environment (mode READY); ``bot_started``
additionally runs the real ``startup_bot()`` so enqueue/registry tests
exercise the production wiring — Anti-Mock Guard: only env vars and
process state are patched, the DB is always real.
"""

from __future__ import annotations

import asyncio

import pytest

import modules._02_bot.registry as bot_registry
import modules._02_bot.settings as bot_settings
import modules._02_bot.signal as bot_signal
from core.admin.registry import AdminRegistry
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.startup import startup_bot


@pytest.fixture
def bot_isolation(monkeypatch):
    """Snapshot/restore every registry and flag the module touches."""
    saved_types = bot_registry.get_notification_types()
    saved_providers = list(bot_registry.get_deadline_audience_providers())
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    monkeypatch.setattr(bot_settings, "_runtime_running", False)
    monkeypatch.setattr(bot_settings, "_misconfigured_logged", False)
    monkeypatch.setattr(bot_settings, "_app_id_warned", False)
    bot_signal.install_wake_event(None)
    yield
    bot_registry.clear_registry()
    for key, variables in saved_types.items():
        bot_registry.register_notification_type(key, variables)
    for provider in saved_providers:
        bot_registry.register_deadline_audience(provider)
    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    bot_signal.install_wake_event(None)


@pytest.fixture
def bot_off_env(monkeypatch):
    """The default environment: no BOT_ENABLED -> BotMode.OFF."""
    for name in (
        "BOT_ENABLED",
        "VK_GROUP_ID",
        "VK_GROUP_TOKEN",
        "VK_CALLBACK_SECRET",
        "VK_CALLBACK_CONFIRMATION",
        "VK_APP_ID",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def bot_env(monkeypatch, bot_isolation):
    """A fully configured bot environment — get_bot_mode() == READY."""
    monkeypatch.setenv("BOT_ENABLED", "1")
    monkeypatch.setenv("VK_GROUP_ID", "12345")
    monkeypatch.setenv("VK_GROUP_TOKEN", "test-group-token")
    monkeypatch.setenv("VK_CALLBACK_SECRET", "test-callback-secret")
    monkeypatch.setenv("VK_CALLBACK_CONFIRMATION", "test-confirm")
    monkeypatch.setenv("VK_APP_ID", "777")


@pytest.fixture
def bot_config(bot_isolation) -> BotConfig:
    """The real ``configs/02_bot.yaml``, loaded and validated."""
    return BotConfig.from_yaml(BotConfig.get_default_config_path())


@pytest.fixture
def bot_started(bot_env) -> BotConfig:
    """``startup_bot()`` over the ready env — real wiring, returns config."""
    return startup_bot()


@pytest.fixture
def wake_event(bot_isolation):
    """An installed ``asyncio.Event`` bell; removed after the test."""
    event = asyncio.Event()
    bot_signal.install_wake_event(event)
    yield event
