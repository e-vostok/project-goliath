"""
Shared fixtures for the 03_registry suite (Issue 2).

Everything the module keeps process-global is snapshotted and restored
by ``registry_isolation``: the table-source registry, the AdminRegistry
hooks and the loaded-config holder. ``registry_started`` runs the real
``startup_registry()`` — the DB is always real (Anti-Mock Guard); only
the config object and env vars are ever swapped, never the session.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules._03_registry.profile_worker as profile_worker_module
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
from modules._04_orders.startup import register_orders_extensions
from tests.fixtures.factories import NationFactory, PlayerFactory

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


@pytest.fixture
def registry_isolation(monkeypatch):
    """Snapshot/restore every process-global the module touches."""
    saved_sources = registry_module.get_table_sources()
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_previews = AdminRegistry.get_player_preview_hooks()
    saved_player_infos = AdminRegistry.get_player_info_hooks()
    saved_province_infos = AdminRegistry.get_province_info_hooks()
    monkeypatch.setattr(startup_module, "_registry_config", None)
    monkeypatch.setattr(startup_module, "_core_config", None)
    # The real config now lists the ``orders`` table — its source is
    # registered by 04_orders strictly before startup_registry()
    # (Spec 04_orders D11), so the fixture wires it the same way.
    register_orders_extensions()
    # Profile-worker globals: mode, last-cycle stamp, the one-shot
    # warnings and the installed wake bell.
    monkeypatch.setattr(
        profile_worker_module, "_mode", profile_worker_module.WorkerMode.OFF
    )
    monkeypatch.setattr(profile_worker_module, "_last_cycle_at", None)
    monkeypatch.setattr(profile_worker_module, "_no_token_warned", False)
    monkeypatch.setattr(profile_worker_module, "_invalid_token_logged", False)
    profile_worker_module.install_wake_event(None)
    yield
    registry_module.clear_registry()
    profile_worker_module.install_wake_event(None)
    for source in saved_sources.values():
        registry_module.register_table_source(source.key, source.provides, source.load)
    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    AdminRegistry._player_preview_hooks.clear()
    AdminRegistry._player_preview_hooks.update(saved_previews)
    AdminRegistry._player_info_hooks.clear()
    AdminRegistry._player_info_hooks.update(saved_player_infos)
    AdminRegistry._province_info_hooks.clear()
    AdminRegistry._province_info_hooks.update(saved_province_infos)


@pytest.fixture
def registry_config(registry_isolation) -> RegistryConfig:
    """The real ``configs/03_registry.yaml``, loaded and validated."""
    return RegistryConfig.from_yaml(RegistryConfig.get_default_config_path())


@pytest.fixture
def registry_started(registry_isolation) -> RegistryConfig:
    """``startup_registry()`` — the real wiring; returns the config."""
    return startup_registry()


@pytest.fixture
def session_factory(test_db_engine):
    """
    A ``get_session_context``-shaped factory over the test engine.

    The shared ``:memory:`` pool serialises every session on one
    connection — sequential transactions work, but tests must seed and
    assert through ``session_factory()`` sessions, never hold
    ``test_db_session`` open while ``run_cycle`` opens its own.
    """
    return async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )


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
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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
        created_at=created_at or datetime.now(UTC),
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
    short_name: str | None = None,
) -> Nation:
    """One nation row; provinces are assigned by the caller.

    ``short_name`` is NOT NULL (migration 0012) — it defaults to a
    fresh unique value from the factory.
    """
    build_kwargs: dict = {"provinces": [], "scheduled_actions": []}
    if short_name is not None:
        build_kwargs["short_name"] = short_name
    nation = NationFactory.build(
        owner=owner,
        name=name,
        color_hex=color_hex,
        created_turn=created_turn,
        created_at=created_at or datetime.now(UTC),
        **build_kwargs,
    )
    session.add(nation)
    await session.flush()
    return nation
