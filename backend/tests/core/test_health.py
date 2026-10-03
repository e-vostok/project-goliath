"""
Integration tests for GET /api/v1/health (DEP-4).

Follows the test_app_startup.py pattern: the REAL app over its real ASGI
lifespan (LifespanManager) against a real Alembic-migrated temporary
SQLite file — no dependency overrides, no mocked DB state (Anti-Mock
Guard). The three scheduler branches are exercised through the real
heartbeat module: touch(now=...) ages the stamp, and the module global
is reset directly for the "never" branch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

import core.health.checks as health_checks
import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from core.tick import heartbeat
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from tests.fixtures.provinces import MAP_MINI_DIR
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch):
    """
    Serve the real app over its real lifespan, backed by a migrated
    temporary SQLite file. No ``get_session`` override — the health
    probe runs against the production engine path, which is exactly
    what it exists to check.
    """
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'health.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    # The lifespan startup syncs the map into provinces — the mini-map
    # fixture keeps that fast and self-contained.
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
    # DEP-4: a stray APP_ENV from the dev .env must never make the test
    # app boot in strict mode.
    monkeypatch.delenv("APP_ENV", raising=False)

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


async def test_health_200_with_real_db_and_fresh_heartbeat(live_client):
    """Public, no auth: everything ok -> 200 with the full body shape."""
    response = await live_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "scheduler": "ok"},
    }
    # The lifespan stamps the heartbeat before creating the scheduler
    # task, so a fresh process is "ok", never "never".


async def test_health_never_before_first_beat(live_client, monkeypatch):
    monkeypatch.setattr(heartbeat, "_last_beat_at", None)

    response = await live_client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "scheduler": "never"},
    }


async def test_health_stale_after_threshold(live_client):
    threshold = CORE_CONFIG.tick.health_max_heartbeat_age_seconds
    heartbeat.touch(
        now=datetime.now(timezone.utc) - timedelta(seconds=threshold + 60)
    )

    response = await live_client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "ok", "scheduler": "stale"},
    }


async def test_health_db_failure_leaks_no_exception_text(
    live_client, monkeypatch
):
    """Fault injection at get_session_context: the only seam the probe
    uses to reach the engine. The 503 body must carry the status word
    "fail" and NOTHING of the underlying error."""

    class _BoomSessionContext:
        async def __aenter__(self):
            raise RuntimeError(
                "simulated outage: password=hunter2 host=internal.db"
            )

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(
        health_checks, "get_session_context", lambda: _BoomSessionContext()
    )

    response = await live_client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "fail", "scheduler": "ok"},
    }
    body = response.text
    assert "simulated outage" not in body
    assert "hunter2" not in body
    assert "internal.db" not in body


async def test_health_sets_cache_control_no_store(live_client):
    response = await live_client.get("/api/v1/health")

    assert response.headers["Cache-Control"] == "no-store"


async def test_internal_health_probe_unchanged(live_client):
    """GET /health stays the static Docker liveness probe (DEP-4 does
    not touch it)."""
    response = await live_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
