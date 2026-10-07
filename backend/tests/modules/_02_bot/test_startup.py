"""
Startup wiring test for 02_bot (Spec 2.5, Appendix T).

The real ASGI lifespan boots with ``BOT_ENABLED`` unset (module OFF —
config is still validated and hooks still land), a second
``startup_bot()`` stays idempotent, and ``/api/v1/health`` keeps its
existing shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._02_bot.startup import startup_bot
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest_asyncio.fixture
async def live_app(tmp_path, monkeypatch, mini_map_config, bot_isolation):
    """
    Boot the real lifespan once with the bot env switched off.
    Mirrors tests/test_app_startup.py's live_client fixture, plus the
    admin state-view/reset snapshot ``bot_isolation`` already provides.
    """
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'bot_startup.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
    for name in (
        "BOT_ENABLED",
        "VK_GROUP_ID",
        "VK_GROUP_TOKEN",
        "VK_CALLBACK_SECRET",
        "VK_CALLBACK_CONFIRMATION",
        "VK_APP_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    saved_resets = AdminRegistry.get_reset_hooks()
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_handlers = {
        phase: list(handlers)
        for phase, handlers in TickOrchestrator._handlers.items()
    }
    saved_finalize = TickOrchestrator._finalize_callback
    saved_extensions = snapshot_extension_points()
    saved_map_service = map_service_module._instance

    async with LifespanManager(app) as manager:
        yield manager.app

    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved_handlers)
    TickOrchestrator._finalize_callback = saved_finalize
    restore_extension_points(saved_extensions)
    map_service_module._instance = saved_map_service


async def test_lifespan_registers_bot_hooks_once(live_app):
    """BOT_ENABLED unset: the app boots, hooks land exactly once, and a
    second startup_bot() does not double-register."""
    views = AdminRegistry.get_state_view_hooks()
    resets = AdminRegistry.get_reset_hooks()
    assert "02_bot" in views
    assert "02_bot" in resets
    views_count = len(views)
    resets_count = len(resets)

    startup_bot()  # second boot must be a no-op

    assert len(AdminRegistry.get_state_view_hooks()) == views_count
    assert len(AdminRegistry.get_reset_hooks()) == resets_count


async def test_health_response_unchanged(live_app):
    """/api/v1/health keeps its shape — the bot adds nothing to it."""
    transport = ASGITransport(app=live_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"
