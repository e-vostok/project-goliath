"""
Shared fixtures for the 03_registry suite (Issue 2).

Everything the module keeps process-global is snapshotted and restored
by ``registry_isolation``: the table-source registry, the AdminRegistry
hooks and the loaded-config holder. ``registry_started`` runs the real
``startup_registry()`` — the DB is always real (Anti-Mock Guard); only
the config object and env vars are ever swapped, never the session.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules._03_registry.registry as registry_module
import modules._03_registry.startup as startup_module
from core.admin.registry import AdminRegistry
from core.db import get_session
from core.security.jwt import issue_token
from main import app
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import Nation, Player
from modules._03_registry.config_schema import RegistryConfig
from modules._03_registry.startup import startup_registry
from tests.fixtures.factories import NationFactory, PlayerFactory

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest.fixture
def registry_isolation(monkeypatch):
    """Snapshot/restore every process-global the module touches."""
    saved_sources = registry_module.get_table_sources()
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    monkeypatch.setattr(startup_module, "_registry_config", None)
    yield
    registry_module.clear_registry()
    for source in saved_sources.values():
        registry_module.register_table_source(
            source.key, source.provides, source.load
        )
    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)


@pytest.fixture
def registry_config(registry_isolation) -> RegistryConfig:
    """The real ``configs/03_registry.yaml``, loaded and validated."""
    return RegistryConfig.from_yaml(RegistryConfig.get_default_config_path())


@pytest.fixture
def registry_started(registry_isolation) -> RegistryConfig:
    """``startup_registry()`` — the real wiring; returns the config."""
    return startup_registry()


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    """A real-length JWT secret for issued Bearer tokens."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-32-bytes-long!!")


@pytest_asyncio.fixture
async def client(test_db_session):
    """HTTP client bound to the real app, backed by the test session."""
    async def _override_get_session():
        yield test_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


def bearer_headers(player_id: str) -> dict[str, str]:
    """An Authorization header with a real issued JWT."""
    token = issue_token(player_id, CORE_CONFIG.auth.jwt_ttl_minutes)
    return {"Authorization": f"Bearer {token}"}


async def seed_player(
    session: AsyncSession,
    vk_user_id: int,
    created_at: datetime | None = None,
) -> Player:
    """One player row with an explicit ``created_at`` order control."""
    player = PlayerFactory.build(
        vk_user_id=vk_user_id,
        created_at=created_at or datetime.now(timezone.utc),
        nations=[],
    )
    session.add(player)
    await session.flush()
    return player


async def seed_nation(
    session: AsyncSession,
    owner: Player,
    name: str,
    color_hex: str,
    *,
    created_turn: int = 0,
    created_at: datetime | None = None,
) -> Nation:
    """One nation row; provinces are assigned by the caller."""
    nation = NationFactory.build(
        owner=owner,
        name=name,
        color_hex=color_hex,
        created_turn=created_turn,
        created_at=created_at or datetime.now(timezone.utc),
        provinces=[],
        scheduled_actions=[],
    )
    session.add(nation)
    await session.flush()
    return nation
