"""
Tests for ``build_table`` and the startup config-vs-sources check
(Spec 2.5 step 3, 3.1; INV-R3, INV-R4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import modules._03_registry.startup as startup_module
from core.admin.registry import AdminRegistry
from modules._03_registry.config_schema import RegistryConfig
from modules._03_registry.errors import (
    RegistryConfigError,
    RegistryProviderError,
    RegistryTableNotFoundError,
)
from modules._03_registry.registry import (
    RegistryRow,
    register_table_source,
)
from modules._03_registry.service import build_table
from modules._03_registry.sources import PLAYERS_PROVIDES, load_players
from modules._03_registry.startup import startup_registry
from tests.modules._03_registry.conftest import seed_nation, seed_player


class TestBuildTable:
    """Spec 3.1 — lookup, cell check, sort, cap, key filtering."""

    async def test_unknown_table_raises_not_found(
        self, test_db_session, registry_started
    ):
        with pytest.raises(RegistryTableNotFoundError) as exc_info:
            await build_table(test_db_session, "ghost_table")
        assert exc_info.value.code == "REGISTRY_TABLE_NOT_FOUND"

    async def test_row_cap_truncates_and_reports_total(
        self, test_db_session, registry_started, monkeypatch
    ):
        # model_copy skips validation — the test-only cap under 50 is
        # deliberate (INV-R4).
        lowered = registry_started.limits.model_copy(
            update={"max_rows_per_table": 2}
        )
        monkeypatch.setattr(
            startup_module,
            "_registry_config",
            registry_started.model_copy(update={"limits": lowered}),
        )
        base = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        for i in range(3):
            await seed_player(
                test_db_session,
                503001 + i,
                created_at=base.replace(hour=12 + i),
            )

        built = await build_table(test_db_session, "players")

        assert built.total == 3
        assert built.truncated is True
        assert [row.key for row in built.rows] == ["p1", "p2"]

    async def test_default_sort_empty_values_last_in_desc(
        self, test_db_session, registry_started, monkeypatch
    ):
        """
        Sorting by the nullable ``nation`` column desc: non-empty cells
        order Beta before Alpha, the nationless player still lands last
        (Spec 3.1 step 4 — empty always last, stable order).
        """
        sorted_cfg = registry_started.table("players").model_copy(
            update={
                "default_sort": registry_started.table(
                    "players"
                ).default_sort.model_copy(
                    update={"column": "nation", "direction": "desc"}
                )
            }
        )
        tables = [
            sorted_cfg if t.id == "players" else t
            for t in registry_started.tables
        ]
        monkeypatch.setattr(
            startup_module,
            "_registry_config",
            registry_started.model_copy(update={"tables": tables}),
        )

        p_alpha = await seed_player(test_db_session, 503101)
        p_beta = await seed_player(test_db_session, 503102)
        await seed_player(test_db_session, 503103)  # no nation
        await seed_nation(
            test_db_session, p_alpha, "Alpha", "#AA0101", created_turn=0
        )
        await seed_nation(
            test_db_session, p_beta, "Beta", "#AA0102", created_turn=0
        )

        built = await build_table(test_db_session, "players")

        nations = [row.cells["nation"] for row in built.rows]
        assert nations == [
            {"name": "Beta", "color": "#AA0102"},
            {"name": "Alpha", "color": "#AA0101"},
            None,
        ]

    async def test_only_configured_column_keys_are_returned(
        self, test_db_session, registry_started
    ):
        """Extra value keys a source emits never reach the response
        (Spec 3.1 step 6)."""
        real_players = load_players

        async def load_with_extra(session):
            rows = await real_players(session)
            return [
                RegistryRow(
                    key=row.key,
                    cells={**row.cells, "not_in_config": "x"},
                )
                for row in rows
            ]

        register_table_source(
            "players", PLAYERS_PROVIDES | {"not_in_config"}, load_with_extra
        )
        await seed_player(test_db_session, 503201)

        built = await build_table(test_db_session, "players")

        assert built.rows and "not_in_config" not in built.rows[0].cells

    async def test_bad_cell_shape_fails_with_provider_error(
        self, test_db_session, registry_started, caplog
    ):
        """A cell violating the Spec 3.6 shape -> REGISTRY_PROVIDER_FAILED
        (Spec 3.1 step 3); the log names table and column, not values."""

        async def bad_load(session):
            return [
                RegistryRow(
                    key="p1",
                    cells={
                        "number": "oops-not-an-int",
                        "player": None,
                        "joined": None,
                        "level": None,
                        "judge_rating": None,
                        "nation": None,
                    },
                )
            ]

        register_table_source("players", PLAYERS_PROVIDES, bad_load)

        with pytest.raises(RegistryProviderError) as exc_info:
            await build_table(test_db_session, "players")
        assert exc_info.value.code == "REGISTRY_PROVIDER_FAILED"
        assert exc_info.value.details == {
            "table_id": "players",
            "column_id": "number",
        }
        assert "oops-not-an-int" not in caplog.text

    async def test_source_exception_becomes_provider_error(
        self, test_db_session, registry_started
    ):
        async def exploding_load(session):
            raise RuntimeError("db gone")

        register_table_source("players", PLAYERS_PROVIDES, exploding_load)

        with pytest.raises(RegistryProviderError) as exc_info:
            await build_table(test_db_session, "players")
        assert exc_info.value.code == "REGISTRY_PROVIDER_FAILED"


class TestStartupCheck:
    """Spec 2.5 step 3 — config vs source registry (INV-R3)."""

    def test_unknown_table_source_aborts_boot(
        self, registry_isolation, monkeypatch
    ):
        bad = RegistryConfig.from_yaml(
            RegistryConfig.get_default_config_path()
        ).model_copy(deep=True)
        bad.tables[0].source = "ghost_source"
        monkeypatch.setattr(
            RegistryConfig,
            "from_yaml",
            classmethod(lambda cls, path: bad),
        )
        with pytest.raises(RegistryConfigError):
            startup_registry()

    def test_unknown_column_source_aborts_boot(
        self, registry_isolation, monkeypatch
    ):
        bad = RegistryConfig.from_yaml(
            RegistryConfig.get_default_config_path()
        ).model_copy(deep=True)
        bad.tables[0].columns[0].source = "ghost_key"
        monkeypatch.setattr(
            RegistryConfig,
            "from_yaml",
            classmethod(lambda cls, path: bad),
        )
        with pytest.raises(RegistryConfigError):
            startup_registry()

    def test_real_config_boots(self, registry_isolation):
        """The shipped config passes the check (Spec 2.5 steps 1–4)."""
        config = startup_registry()
        assert "03_registry" in AdminRegistry.get_state_view_hooks()


class TestAdminStateView:
    """Spec 5.4 — counters only; no names, photo urls or VK ids."""

    async def test_state_view_shape(
        self, test_db_session, registry_started
    ):
        from tests.fixtures.factories import make_vk_profile

        player = await seed_player(test_db_session, 504001)
        await make_vk_profile(
            test_db_session, player, status="PENDING"
        )
        await seed_nation(
            test_db_session, player, "Альфа", "#BB0001", created_turn=0
        )

        view = AdminRegistry.get_state_view_hooks()["03_registry"]
        snapshot = await view(test_db_session)

        assert snapshot["tables"] == ["players", "nations"]
        assert snapshot["players_total"] == 1
        assert snapshot["nations_total"] == 1
        assert snapshot["profiles"] == {
            "PENDING": 1,
            "OK": 0,
            "UNAVAILABLE": 0,
        }
        assert snapshot["profile_worker_mode"] == "OFF"
        blob = json.dumps(snapshot, ensure_ascii=False)
        assert "Иван" not in blob
        assert str(player.vk_user_id) not in blob
        assert player.id not in blob
