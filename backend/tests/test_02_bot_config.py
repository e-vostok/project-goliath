"""
Tests for the 02_bot configuration contract (Spec Part 4, Issue 1).

The pair ``configs/02_bot.yaml`` ↔ ``BotConfig`` must be config-safe:
strict ranges, ``extra="forbid"`` on every section, cross-field rules
and template checks. A bad value must fail here — in CI — before the
server starts (Spec Appendix T, T19/T20).

Pattern follows tests/test_01_map_config.py: every synthetic config is
one mutation of the real YAML dict, validated through
``BotConfig.model_validate`` — no hand-written base config to drift.
"""

from __future__ import annotations

import copy
import os

import pytest
import yaml
from pydantic import ValidationError

from modules._02_bot.config_schema import BUILTIN_TYPE_VARIABLES, BotConfig


def _load_raw() -> dict:
    """The real ``configs/02_bot.yaml`` as a plain dict."""
    with open(
        BotConfig.get_default_config_path(), encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)


def _mutated(mutate) -> dict:
    """A deep copy of the real YAML dict with ``mutate`` applied."""
    data = copy.deepcopy(_load_raw())
    mutate(data)
    return data


class TestRealConfig:
    def test_real_yaml_loads(self):
        config = BotConfig.from_yaml(BotConfig.get_default_config_path())

        assert set(BUILTIN_TYPE_VARIABLES) <= set(config.types)
        assert config.types["DEADLINE_WARNING"].enabled is False
        assert "{group_id}" in config.client.chat_url_template
        assert config.consent.required_for_registration is True
        assert config.vk.api_version.startswith("5.")

    @pytest.mark.parametrize(
        "cwd_name",
        [
            os.path.join("backend", "src"),
            os.path.join("backend", "tests"),
        ],
    )
    def test_default_path_resolves_from_any_cwd(
        self, tmp_path, monkeypatch, cwd_name
    ):
        """get_default_config_path is resolved relative to the schema
        file, so loading works from src/ and tests/ alike."""
        from pathlib import Path

        repo_root = Path(BotConfig.get_default_config_path()).parents[1]
        monkeypatch.chdir(repo_root / cwd_name)

        config = BotConfig.from_yaml(BotConfig.get_default_config_path())
        assert set(BUILTIN_TYPE_VARIABLES) <= set(config.types)


class TestRejects:
    """Each case breaks exactly one rule of the shipped config."""

    @staticmethod
    def _expect_error(mutate, needle: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            BotConfig.model_validate(_mutated(mutate))
        assert needle in str(exc_info.value)

    def test_unknown_key_rejected(self):
        """A typo key (vk.api_vrsion) must not be silently ignored."""
        self._expect_error(
            lambda d: d["vk"].__setitem__("api_vrsion", "5.199"),
            "api_vrsion",
        )

    def test_unknown_template_variable_rejected(self):
        self._expect_error(
            lambda d: d["types"]["TICK_DIGEST"].__setitem__(
                "text", d["types"]["TICK_DIGEST"]["text"] + " {bogus_var}"
            ),
            "bogus_var",
        )

    def test_stray_brace_in_template_rejected(self):
        self._expect_error(
            lambda d: d["dialog"]["texts"].__setitem__(
                "plate", d["dialog"]["texts"]["plate"] + " }"
            ),
            "plate",
        )

    def test_lease_seconds_below_batch_bound_rejected(self):
        """lease_seconds must exceed ceil(batch/concurrency)*timeout
        (here ceil(20/5)*10 = 40), so 40 already fails."""
        self._expect_error(
            lambda d: d["sender"].__setitem__("lease_seconds", 40),
            "lease_seconds",
        )

    def test_critical_type_cannot_merge(self):
        """priority=critical forbids merge != never (RED_ALERT)."""
        self._expect_error(
            lambda d: d["types"]["RED_ALERT"].__setitem__(
                "merge", "always"
            ),
            "merge",
        )

    def test_deadline_ttl_above_offset_rejected(self):
        self._expect_error(
            lambda d: d["types"]["DEADLINE_WARNING"].__setitem__(
                "ttl_minutes",
                d["deadline"]["offset_minutes"] + 1,
            ),
            "DEADLINE_WARNING",
        )

    def test_rules_url_host_outside_allowlist_rejected(self):
        self._expect_error(
            lambda d: d["dialog"]["help"].__setitem__(
                "rules_url", "https://example.org/rules"
            ),
            "rules_url",
        )

    @pytest.mark.parametrize("builtin", sorted(BUILTIN_TYPE_VARIABLES))
    def test_missing_builtin_type_rejected(self, builtin):
        self._expect_error(
            lambda d: d["types"].__delitem__(builtin),
            builtin,
        )

    def test_chat_url_template_without_group_id_rejected(self):
        self._expect_error(
            lambda d: d["client"].__setitem__(
                "chat_url_template", "https://vk.com/write-1"
            ),
            "chat_url_template",
        )

    def test_invisible_character_in_plate_rejected(self):
        """U+200B (zero-width space) is a Cf symbol — templates must
        carry no invisible characters."""
        self._expect_error(
            lambda d: d["dialog"]["texts"].__setitem__(
                "plate", d["dialog"]["texts"]["plate"] + chr(0x200B)
            ),
            "plate",
        )
