"""
Tests for 02_bot settings / run modes (Spec 1.4, INV-B10).

Modes OFF -> MISCONFIGURED -> READY -> RUNNING come purely from the
environment plus the runtime flag; the MISCONFIGURED CRITICAL line must
name the missing variables but never their values (INV-B9).
"""

from __future__ import annotations

import logging

import modules._02_bot.settings as settings
from modules._02_bot.settings import (
    BotMode,
    get_bot_mode,
    is_bot_active,
    read_bot_env,
    set_runtime_running,
)


class TestReadBotEnv:
    def test_defaults_disabled(self, bot_isolation, bot_off_env):
        env = read_bot_env()
        assert env.enabled is False
        assert env.group_id is None
        assert env.group_token is None

    def test_enabled_truthy_variants(
        self, bot_isolation, bot_off_env, monkeypatch
    ):
        monkeypatch.setenv("BOT_ENABLED", "Yes")
        assert read_bot_env().enabled is True
        monkeypatch.setenv("BOT_ENABLED", "0")
        assert read_bot_env().enabled is False
        monkeypatch.setenv("BOT_ENABLED", "nonsense")
        assert read_bot_env().enabled is False

    def test_secrets_not_in_repr(self, bot_isolation, bot_env):
        env = read_bot_env()
        rendered = repr(env)
        assert "test-group-token" not in rendered
        assert "test-callback-secret" not in rendered

    def test_app_id_blank_or_junk_warns_once(
        self, bot_isolation, bot_env, monkeypatch, caplog
    ):
        monkeypatch.delenv("VK_APP_ID", raising=False)
        with caplog.at_level(logging.WARNING):
            assert read_bot_env().app_id is None
            assert read_bot_env().app_id is None
        warnings = [
            r for r in caplog.records if "VK_APP_ID" in r.getMessage()
        ]
        assert len(warnings) == 1


class TestGetBotMode:
    def test_default_is_off(self, bot_isolation, bot_off_env):
        assert get_bot_mode() == BotMode.OFF
        assert is_bot_active() is False

    def test_misconfigured_logs_names_not_values(
        self, bot_isolation, bot_env, monkeypatch, caplog
    ):
        monkeypatch.delenv("VK_GROUP_ID")
        with caplog.at_level(logging.CRITICAL):
            mode = get_bot_mode()
        assert mode == BotMode.MISCONFIGURED
        assert is_bot_active() is False
        critical = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.CRITICAL
        ]
        assert len(critical) == 1
        assert "VK_GROUP_ID" in critical[0]
        assert "test-group-token" not in critical[0]
        assert "test-callback-secret" not in critical[0]

    def test_ready_when_configured(self, bot_env):
        assert get_bot_mode() == BotMode.READY
        assert is_bot_active() is True

    def test_running_after_runtime_flag(self, bot_env):
        set_runtime_running(True)
        assert get_bot_mode() == BotMode.RUNNING
        assert is_bot_active() is True

    def test_running_flag_does_not_wake_disabled_bot(
        self, bot_isolation, bot_off_env
    ):
        set_runtime_running(True)
        assert get_bot_mode() == BotMode.OFF
        assert is_bot_active() is False
