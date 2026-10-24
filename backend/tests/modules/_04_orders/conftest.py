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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import modules._02_bot.registry as bot_registry
import modules._02_bot.startup as bot_startup_module
import modules._03_registry.registry as registry_module
import modules._03_registry.startup as registry_startup_module
import modules._04_orders.startup as orders_startup_module
import modules._04_orders.worker as orders_worker_module
from core.admin.registry import AdminRegistry
from core.db import get_session
from main import app
from modules._00_core.models import Nation, Player
from modules._02_bot.startup import startup_bot
from modules._04_orders.startup import (
    register_orders_extensions,
    startup_orders,
)
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    make_consent,
)

# Re-export the bot suite's env fixtures so orders tests exercise the
# real bot path (READY mode) instead of a stub (Anti-Mock Guard).
from tests.modules._02_bot.conftest import (  # noqa: F401
    bot_env,
    bot_isolation,
    bot_off_env,
)


@pytest.fixture
def orders_isolation(monkeypatch):
    """Snapshot/restore every process-global the module touches."""
    saved_sources = registry_module.get_table_sources()
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_previews = AdminRegistry.get_player_preview_hooks()
    saved_player_infos = AdminRegistry.get_player_info_hooks()
    # register_orders_extensions() writes into the bot registry —
    # snapshot and restore it like the rest of the process globals.
    saved_types = bot_registry.get_notification_types()
    monkeypatch.setattr(orders_startup_module, "_orders_config", None)
    monkeypatch.setattr(orders_startup_module, "_orders_allowed_hosts", None)
    monkeypatch.setattr(registry_startup_module, "_registry_config", None)
    monkeypatch.setattr(registry_startup_module, "_core_config", None)
    monkeypatch.setattr(bot_startup_module, "_bot_config", None)
    # Worker globals: mode, last-pass stamp and the installed bell.
    monkeypatch.setattr(
        orders_worker_module, "_mode", orders_worker_module.WorkerMode.STOPPED
    )
    monkeypatch.setattr(orders_worker_module, "_last_pass_at", None)
    orders_worker_module.install_wake_event(None)
    yield
    orders_worker_module.install_wake_event(None)
    registry_module.clear_registry()
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
    bot_registry.clear_registry()
    for key, variables in saved_types.items():
        bot_registry.register_notification_type(key, variables)


@pytest.fixture
def orders_started(orders_isolation):
    """``startup_orders()`` — the real wiring; returns the config."""
    return startup_orders()


@pytest.fixture
def session_factory(test_db_engine):
    """
    A ``get_session_context``-shaped factory over the test engine.

    ``run_retry_pass`` opens its own sessions, so tests seed and assert
    through ``session_factory()`` sessions that commit — the shared
    ``:memory:`` pool serialises everything on one connection and
    ``test_db_session`` must not stay open while the pass runs.
    """
    return async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
def orders_bot_started(orders_isolation, bot_env):  # noqa: F811
    """
    The production wiring order of ``lifespan`` (Spec D11): extensions
    first — so ``startup_bot()`` validates the ORDER_* types against
    the real ``configs/02_bot.yaml`` — then both module startups.
    Returns the bot config (the orders config is loaded too).
    """
    register_orders_extensions()
    bot_config = startup_bot()
    startup_orders()
    return bot_config


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
        # A catalog flag id — deterministic (the factory's random
        # optional would sometimes yield None or an unknown id) so the
        # flag_url snapshot path is exercised.
        flag_id="flag_placeholder_1",
        provinces=[],
        scheduled_actions=[],
    )
    session.add(nation)
    await session.flush()
    return player, nation


async def seed_judge(
    session: AsyncSession,
    vk_user_id: int,
    *,
    rating: int | None = None,
    nation: bool = False,
    consent: str | None = None,
) -> Player:
    """
    A potential judge: optional rating override (None keeps the factory
    default), a nation of their own and/or a bot-consent state — the
    three ingredients of the reachability rule (Spec 3.2).
    """
    build_kwargs: dict = {"vk_user_id": vk_user_id, "nations": []}
    if rating is not None:
        build_kwargs["judge_rating"] = rating
    player = PlayerFactory.build(**build_kwargs)
    session.add(player)
    await session.flush()
    if nation:
        session.add(
            NationFactory.build(
                owner=player,
                name=f"Судейство {vk_user_id}",
                color_hex=f"#{vk_user_id % 0xFFFFFF:06X}",
                provinces=[],
                scheduled_actions=[],
            )
        )
        await session.flush()
    if consent is not None:
        await make_consent(session, player, state=consent)
    return player
