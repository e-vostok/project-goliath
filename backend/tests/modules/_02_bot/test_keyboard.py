"""
Tests for the VK keyboards of 02_bot (Spec 5.5, Appendix T: T25).

The persistent panel is one row: MEMBER gets «Статус»/«Помощь» text
buttons; GUEST gets the «Создать государство» open_app button only when
VK_APP_ID is configured, plus «Помощь». The help answer carries an
inline open_link keyboard that hides null links and returns None when
all are null. ``dumps`` is the final guard of the VK limits.
"""

from __future__ import annotations

import json

import pytest

from modules._02_bot.config_schema import BotConfig
from modules._02_bot.keyboard import (
    build_help_inline_keyboard,
    build_persistent_keyboard,
    dumps,
)


class TestPersistent:
    def test_member_row(self, bot_config):
        kb = build_persistent_keyboard("MEMBER", bot_config, app_id=777)
        assert kb["one_time"] is False
        assert kb["inline"] is False
        [row] = kb["buttons"]
        assert [b["action"]["type"] for b in row] == ["text", "text"]
        assert row[0]["action"]["label"] == "Статус"
        assert row[1]["action"]["label"] == "Помощь"
        assert json.loads(row[0]["action"]["payload"]) == {
            "cmd": "status"
        }
        assert json.loads(row[1]["action"]["payload"]) == {"cmd": "help"}

    def test_guest_with_app_id(self, bot_config):
        kb = build_persistent_keyboard("GUEST", bot_config, app_id=777)
        [row] = kb["buttons"]
        assert [b["action"]["type"] for b in row] == [
            "open_app",
            "text",
        ]
        action = row[0]["action"]
        assert action["label"] == "Создать государство"
        assert action["app_id"] == 777
        assert action["hash"] == "register"
        assert "payload" not in action

    def test_guest_without_app_id_has_no_register_button(
        self, bot_config
    ):
        kb = build_persistent_keyboard("GUEST", bot_config, app_id=None)
        [row] = kb["buttons"]
        assert [b["action"]["type"] for b in row] == ["text"]
        assert row[0]["action"]["label"] == "Помощь"


class TestHelpInline:
    def test_null_links_hidden(self, bot_config):
        """Real YAML: regulations_url is null -> two rows only."""
        kb = build_help_inline_keyboard(bot_config)
        assert kb is not None
        assert kb["inline"] is True
        assert "one_time" not in kb
        assert len(kb["buttons"]) == 2
        for [button] in kb["buttons"]:
            assert button["action"]["type"] == "open_link"
            assert button["action"]["link"].startswith("https://")

    def test_all_null_returns_none(self, bot_config):
        config = bot_config.model_copy(
            update={
                "dialog": bot_config.dialog.model_copy(
                    update={
                        "help": bot_config.dialog.help.model_copy(
                            update={
                                "rules_url": None,
                                "regulations_url": None,
                                "admin_contact_url": None,
                            }
                        )
                    }
                )
            }
        )
        assert build_help_inline_keyboard(config) is None


class TestDumps:
    def test_compact_json_roundtrip(self, bot_config):
        kb = build_persistent_keyboard("MEMBER", bot_config, app_id=None)
        raw = dumps(kb)
        assert " " not in raw.split('"buttons"', 1)[0]
        assert json.loads(raw) == kb

    def test_label_over_limit_rejected(self, bot_config):
        kb = {
            "buttons": [
                [{"action": {"type": "text", "label": "x" * 41}}]
            ]
        }
        with pytest.raises(ValueError):
            dumps(kb)

    @pytest.mark.parametrize(
        "payload",
        ["{" + "x" * 300 + "}", '"cmd":"status"'],
    )
    def test_bad_payload_rejected(self, payload):
        kb = {
            "buttons": [
                [
                    {
                        "action": {
                            "type": "text",
                            "label": "ok",
                            "payload": payload,
                        }
                    }
                ]
            ]
        }
        with pytest.raises(ValueError):
            dumps(kb)
