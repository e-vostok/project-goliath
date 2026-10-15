"""
Shared fixtures for the 04_orders suite (Issue 4).

Everything the module keeps process-global is snapshotted and restored
by ``orders_isolation``: the loaded ``OrdersConfig``/allowed-hosts
holders, the Registry source registry (module sources registered under
test are rolled back), the loaded RegistryConfig holder and the
AdminRegistry hooks. ``orders_started`` runs the real
``startup_orders()`` — the DB is always real (Anti-Mock Guard).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import modules._03_registry.registry as registry_module
import modules._03_registry.startup as registry_startup_module
import modules._04_orders.startup as orders_startup_module
from core.admin.registry import AdminRegistry
from core.db import get_session
from main import app
from modules._00_core.models import Nation, Player
from modules._04_orders.startup import startup_orders
from tests.fixtures.factories import NationFactory, PlayerFactory


@pytest.fixture
def orders_isolation(monkeypatch):
    """Snapshot/restore every process-global the module touches."""
    saved_sources = registry_module.get_table_sources()
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    monkeypatch.setattr(orders_startup_module, "_orders_config", None)
    monkeypatch.setattr(
        orders_startup_module, "_orders_allowed_hosts", None
    )
    monkeypatch.setattr(registry_startup_module, "_registry_config", None)
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
def orders_started(orders_isolation):
    """``startup_orders()`` — the real wiring; returns the config."""
    return startup_orders()


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    """A real-length JWT secret for issued Bearer tokens."""
    monkeypatch.setenv(
        "JWT_SECRET_KEY", "test-jwt-secret-key-32-bytes-long!!"
    )


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


async def seed_author(
    session: AsyncSession,
    vk_user_id: int,
    *,
    nation_name: str = "Автория",
    nation_color: str = "#336699",
) -> tuple[Player, Nation]:
    """A player owning a nation — the only shape ``submit`` accepts."""
    player = PlayerFactory.build(vk_user_id=vk_user_id, nations=[])
    session.add(player)
    await session.flush()
    nation = NationFactory.build(
        owner=player,
        name=nation_name,
        color_hex=nation_color,
        provinces=[],
        scheduled_actions=[],
    )
    session.add(nation)
    await session.flush()
    return player, nation
