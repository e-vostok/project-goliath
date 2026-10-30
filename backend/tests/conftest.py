"""
Pytest configuration and fixtures for async tests.

Provides async SQLite in-memory database fixture with schema creation.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.db import Base


@pytest_asyncio.fixture(scope="function")
async def test_db_engine() -> AsyncGenerator[Any, None]:
    """
    Create an async SQLite in-memory database engine for testing.

    The database is created fresh for each test function.
    """
    database_url = "sqlite+aiosqlite:///:memory:"

    engine = create_async_engine(
        database_url,
        echo=False,
        future=True,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_db_session(test_db_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    """
    Create an async session for the test database.

    Creates tables using SQLAlchemy metadata before yielding the session.
    Wraps each test in a transaction that gets rolled back.
    """
    session_maker = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        # Begin a transaction
        await session.begin()

        yield session

        # Rollback the transaction to clean up
        await session.rollback()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Configure pytest-asyncio to use asyncio backend."""
    return "asyncio"


# --- Process-wide state isolation -----------------------------------------
#
# The app's lifespan registers every hook, listener and worker into
# PROCESS-wide holders (00_core extension points, AdminRegistry,
# TickOrchestrator, module singletons). A test that boots the app and
# fails to restore — e.g. a live_client fixture whose teardown dies on
# an asgi_lifespan shutdown timeout before its restore lines run —
# leaks the whole wiring into every later test. ``_process_state``
# snapshots each registry once, after ``main`` is imported (the state
# the app import leaves), and restores that baseline after every test.
# Lifespan task names leaked by an aborted shutdown are cancelled too.

_ADMIN_DICT_NAMES = (
    "_reset_hooks",
    "_state_view_hooks",
    "_player_preview_hooks",
    "_nation_preview_hooks",
    "_overview_hooks",
    "_player_info_hooks",
    "_province_info_hooks",
    "_audit_action_hooks",
)

_LIFESPAN_TASK_NAMES = frozenset(
    {"tick-scheduler", "orders-retry", "registry-profiles"}
)


def _snapshot_process_state() -> dict:
    """Opaque snapshot of every process-wide registry a test may touch."""
    import core.db as core_db
    import modules._01_map.service as map_service_module
    import modules._02_bot.settings as bot_settings
    import modules._02_bot.signal as bot_signal
    import modules._02_bot.startup as bot_startup
    import modules._03_registry.profile_worker as profile_worker
    import modules._03_registry.registry as registry_module
    import modules._03_registry.startup as registry_startup
    import modules._04_orders.startup as orders_startup
    import modules._04_orders.worker as orders_worker
    from core.admin.registry import AdminRegistry
    from core.tick import heartbeat
    from core.tick.orchestrator import TickOrchestrator
    from main import app
    from modules._00_core.hooks import snapshot_extension_points
    from modules._02_bot.registry import (
        get_deadline_audience_providers,
        get_notification_types,
    )

    return {
        "extensions": snapshot_extension_points(),
        "admin": {
            name: dict(getattr(AdminRegistry, name))
            for name in _ADMIN_DICT_NAMES
        },
        "tick_handlers": {
            phase: list(handlers)
            for phase, handlers in TickOrchestrator._handlers.items()
        },
        "tick_finalize": TickOrchestrator._finalize_callback,
        "map_instance": map_service_module._instance,
        "db_engine": core_db._engine,
        "db_session_maker": core_db._async_session_maker,
        "bot_config": bot_startup._bot_config,
        "bot_types": get_notification_types(),
        "bot_audience": get_deadline_audience_providers(),
        "bot_flags": (
            bot_settings._runtime_running,
            bot_settings._misconfigured_logged,
            bot_settings._app_id_warned,
        ),
        "bot_runtime": bot_settings._active_runtime,
        "bot_wake": bot_signal._wake_event,
        "registry_sources": registry_module.get_table_sources(),
        "registry_config": (
            registry_startup._registry_config,
            registry_startup._core_config,
        ),
        "profile_worker": (
            profile_worker._mode,
            profile_worker._wake_event,
            profile_worker._last_cycle_at,
            profile_worker._no_token_warned,
            profile_worker._invalid_token_logged,
        ),
        "orders_config": (
            orders_startup._orders_config,
            orders_startup._orders_allowed_hosts,
        ),
        "orders_worker": (
            orders_worker._mode,
            orders_worker._wake_event,
            orders_worker._last_pass_at,
        ),
        "heartbeat": heartbeat._last_beat_at,
        "dep_overrides": dict(app.dependency_overrides),
    }


def _restore_process_state(saved: dict) -> None:
    """Restore a snapshot taken by :func:`_snapshot_process_state`."""
    import core.db as core_db
    import modules._01_map.service as map_service_module
    import modules._02_bot.registry as bot_registry
    import modules._02_bot.settings as bot_settings
    import modules._02_bot.signal as bot_signal
    import modules._02_bot.startup as bot_startup
    import modules._03_registry.profile_worker as profile_worker
    import modules._03_registry.registry as registry_module
    import modules._03_registry.startup as registry_startup
    import modules._04_orders.startup as orders_startup
    import modules._04_orders.worker as orders_worker
    from core.admin.registry import AdminRegistry
    from core.tick import heartbeat
    from core.tick.orchestrator import TickOrchestrator
    from main import app
    from modules._00_core.hooks import restore_extension_points

    restore_extension_points(saved["extensions"])
    for name in _ADMIN_DICT_NAMES:
        registry = getattr(AdminRegistry, name)
        registry.clear()
        registry.update(saved["admin"][name])
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved["tick_handlers"])
    TickOrchestrator._finalize_callback = saved["tick_finalize"]
    map_service_module._instance = saved["map_instance"]
    core_db._engine = saved["db_engine"]
    core_db._async_session_maker = saved["db_session_maker"]
    bot_startup._bot_config = saved["bot_config"]
    bot_registry.clear_registry()
    for key, variables in saved["bot_types"].items():
        bot_registry.register_notification_type(key, variables)
    for provider in saved["bot_audience"]:
        bot_registry.register_deadline_audience(provider)
    (
        bot_settings._runtime_running,
        bot_settings._misconfigured_logged,
        bot_settings._app_id_warned,
    ) = saved["bot_flags"]
    bot_settings._active_runtime = saved["bot_runtime"]
    bot_signal._wake_event = saved["bot_wake"]
    registry_module.clear_registry()
    for source in saved["registry_sources"].values():
        registry_module.register_table_source(
            source.key, source.provides, source.load
        )
    (
        registry_startup._registry_config,
        registry_startup._core_config,
    ) = saved["registry_config"]
    (
        profile_worker._mode,
        profile_worker._wake_event,
        profile_worker._last_cycle_at,
        profile_worker._no_token_warned,
        profile_worker._invalid_token_logged,
    ) = saved["profile_worker"]
    (
        orders_startup._orders_config,
        orders_startup._orders_allowed_hosts,
    ) = saved["orders_config"]
    (
        orders_worker._mode,
        orders_worker._wake_event,
        orders_worker._last_pass_at,
    ) = saved["orders_worker"]
    heartbeat._last_beat_at = saved["heartbeat"]
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved["dep_overrides"])


_BASELINE: dict | None = None


def _process_state_baseline() -> dict:
    """The registry state left by importing the app, snapshotted once."""
    global _BASELINE
    if _BASELINE is None:
        import main  # noqa: F401 — the app import fills what it fills
        _BASELINE = _snapshot_process_state()
    return _BASELINE


@pytest_asyncio.fixture(autouse=True)
async def _process_state_isolation():
    """
    Restore the post-import baseline of every process-wide registry
    after each test, cancel lifespan tasks that outlived their test,
    and keep the ambient ``VK_GROUP_TOKEN`` out of tests — a real token
    would start the 03_registry profile worker against the live VK API
    (tests must never reach it; test_app_startup.py does the same).
    """
    saved_token = os.environ.pop("VK_GROUP_TOKEN", None)
    yield
    if saved_token is None:
        os.environ.pop("VK_GROUP_TOKEN", None)
    else:
        os.environ["VK_GROUP_TOKEN"] = saved_token
    loop_tasks = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not task.done()
        and (
            task.get_name() in _LIFESPAN_TASK_NAMES
            or task.get_name().startswith("bot-")
        )
    ]
    for task in loop_tasks:
        task.cancel()
    if loop_tasks:
        await asyncio.wait(loop_tasks, timeout=5)
    _restore_process_state(_process_state_baseline())


@pytest.fixture
def mini_map_config(monkeypatch):
    """
    For tests that boot ``startup_map()`` / the ASGI lifespan against
    ``MAP_DATA_DIR=tests/fixtures/map_mini``: ``MapConfig.from_yaml``
    returns the real ``configs/01_map.yaml`` with ``view.frame`` swapped
    for a rect inside the mini fixture's view_box (the real frame is
    calibrated to the real map and would fail the loader's
    frame-inside-view_box check there).
    """
    from modules._01_map.config_schema import MapConfig
    from tests.modules._01_map.conftest import map_config

    config = map_config()
    monkeypatch.setattr(MapConfig, "from_yaml", classmethod(lambda cls, path: config))
    return config
