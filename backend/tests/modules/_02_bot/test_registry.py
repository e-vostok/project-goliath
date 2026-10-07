"""
Tests for the 02_bot extension registries (Spec 2.6).

Validation is startup-fatal (BotRegistryError): a registered key absent
from ``configs/02_bot.yaml``, or a template placeholder outside the
registered variables, must stop the boot. A YAML type nobody registered
is legal. Synthetic configs are mutations of the real YAML dict through
``BotConfig.model_validate`` — the Issue-1 pattern.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from modules._02_bot.config_schema import BotConfig
from modules._02_bot.registry import (
    BotRegistryError,
    clear_registry,
    get_deadline_audience_providers,
    get_notification_type,
    register_builtin_types,
    register_deadline_audience,
    register_notification_type,
    validate_registry_against_config,
)


def _load_raw() -> dict:
    with open(
        BotConfig.get_default_config_path(), encoding="utf-8"
    ) as f:
        return yaml.safe_load(f)


def _config_with_type() -> BotConfig:
    """Real YAML plus one valid satellite type ZONE_ALARM."""
    data = copy.deepcopy(_load_raw())
    data["types"]["ZONE_ALARM"] = {
        "enabled": True,
        "priority": "normal",
        "requires_consent": True,
        "counts_toward_cap": False,
        "ttl_minutes": 60,
        "hold_seconds": 0,
        "merge": "never",
        "max_per_window": 0,
        "window_minutes": 60,
        "text": "Зона {zone} тревожит.",
        "batch_text": None,
        "line_text": None,
    }
    return BotConfig.model_validate(data)


@pytest.fixture(autouse=True)
def clean_registry(bot_isolation):
    clear_registry()
    yield
    clear_registry()


class TestNotificationTypes:
    def test_registered_key_missing_from_yaml_rejected(self):
        register_notification_type("GHOST_TYPE", frozenset({"x"}))
        config = BotConfig.from_yaml(BotConfig.get_default_config_path())
        with pytest.raises(BotRegistryError, match="GHOST_TYPE"):
            validate_registry_against_config(config)

    def test_placeholder_outside_variables_rejected(self):
        config = _config_with_type()
        register_notification_type("ZONE_ALARM", frozenset())
        with pytest.raises(BotRegistryError, match="zone"):
            validate_registry_against_config(config)

    def test_unregistered_yaml_type_accepted(self):
        # ZONE_ALARM stays in the YAML unregistered — it waits for its
        # owning module and is simply unused (Spec 2.6).
        config = _config_with_type()
        register_builtin_types()
        validate_registry_against_config(config)

    def test_registered_satellite_type_validates(self):
        config = _config_with_type()
        register_builtin_types()
        register_notification_type("ZONE_ALARM", frozenset({"zone"}))
        validate_registry_against_config(config)

    def test_reregister_same_variables_is_noop(self):
        register_notification_type("ZONE_ALARM", frozenset({"zone"}))
        register_notification_type("ZONE_ALARM", {"zone", "zone"})
        assert get_notification_type("ZONE_ALARM") == frozenset({"zone"})

    def test_reregister_conflicting_variables_rejected(self):
        register_notification_type("ZONE_ALARM", frozenset({"zone"}))
        with pytest.raises(BotRegistryError, match="ZONE_ALARM"):
            register_notification_type("ZONE_ALARM", frozenset({"other"}))


class TestDeadlineAudience:
    def test_providers_registered_once(self):
        async def provider(session, turn):
            return set()

        register_deadline_audience(provider)
        register_deadline_audience(provider)
        assert get_deadline_audience_providers() == (provider,)
