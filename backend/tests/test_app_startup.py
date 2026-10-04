"""
Startup-path integration test for the FastAPI app.

Boots the real ``app`` through the actual ASGI lifespan protocol with NO
dependency overrides, against a real file-based SQLite database with
Alembic migrations applied. This is the only test that exercises
``init_engine()`` on production startup — every other suite replaces
``get_session`` and would never notice a missing engine init.
"""

from __future__ import annotations

from pathlib import Path

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
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """
    Serve the real app over its real lifespan, backed by a migrated
    temporary SQLite file. No ``get_session`` override — requests go
    through the production engine initialized by lifespan startup.
    """
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'startup.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    # The lifespan startup syncs the map into provinces — the mini-map
    # fixture keeps that fast and self-contained.
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    saved_resets = AdminRegistry.get_reset_hooks()
    saved_handlers = {
        phase: list(handlers)
        for phase, handlers in TickOrchestrator._handlers.items()
    }
    saved_finalize = TickOrchestrator._finalize_callback
    saved_extensions = snapshot_extension_points()
    saved_map_service = map_service_module._instance

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client

    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved_handlers)
    TickOrchestrator._finalize_callback = saved_finalize
    restore_extension_points(saved_extensions)
    map_service_module._instance = saved_map_service


async def test_auth_vk_served_by_real_startup(live_client):
    """Real server (no overrides) answers /auth/vk end-to-end."""
    launch_params = make_launch_params(vk_user_id=999001, secret=TEST_VK_SECRET)

    response = await live_client.post(
        "/api/v1/auth/vk", json={"launch_params": launch_params}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["player"]["vk_user_id"] == 999001
