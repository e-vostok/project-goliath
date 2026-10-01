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

from main import app
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch):
    """
    Serve the real app over its real lifespan, backed by a migrated
    temporary SQLite file. No ``get_session`` override — requests go
    through the production engine initialized by lifespan startup.
    """
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'startup.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


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
