"""
«Forgotten table» guard (0.11.0 unit 6b).

Every table in ``Base.metadata`` must be classified against the two
destructive admin paths — the world reset and the player deletion —
so a future module can never add a table and forget what happens to
its rows. ``TABLE_COVERAGE`` below is the explicit dictionary; each
entry was derived by reading the real reset hooks
(``AdminRegistry.get_reset_hooks()`` registrations in every module's
``admin_hooks.py``/``hooks.py``) and ``PlayerService.delete_player``
plus its ``register_player_delete_hook`` chain:

- ``reset`` — the world reset empties the table (the behavioural test
  below proves it: after ``POST /admin/state/reset`` every ``reset``
  table is empty).
- ``player_delete`` — the row set tied to one player is removed or
  released when ``PlayerService.delete_player`` runs.
- ``kept`` — survives both by design; the tuple's second element is
  the mandatory one-line reason.

A new table that lands in ``Base.metadata`` without an entry fails
``test_every_metadata_table_is_classified`` with the instructions.

Live-app tests reuse the test_players_list.py ``live_client``
pattern: real lifespan, migrated DB, real JWTs (Anti-Mock Guard).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from alembic.config import Config
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

import modules._00_core.models  # noqa: F401 — registers all ORM tables
import modules._01_map.models  # noqa: F401
import modules._02_bot.models  # noqa: F401
import modules._03_registry.models  # noqa: F401
import modules._04_orders.models  # noqa: F401
import modules._01_map.service as map_service_module
from alembic import command
from core.admin.registry import AdminRegistry
from core.db import Base, get_session_context
from core.tick.orchestrator import TickOrchestrator
from main import app
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import (
    Nation,
    ScheduledAction,
    TickLog,
)
from modules._01_map.models import MapOwnershipLog
from modules._02_bot.models import BotOutbox
from modules._04_orders.models import Order
from tests.core.admin.test_router import (
    ADMIN_VK_ID,
    BACKEND_DIR,
    PG_TEST_URL,
    _async_url,
    _reset_pg_schema,
)
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    ScheduledActionFactory,
    TickLogFactory,
    make_order,
    make_outbox_row,
)
from tests.fixtures.provinces import MAP_MINI_DIR, map_mini_node_ids
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    make_launch_params,
)

# ── The coverage dictionary ──────────────────────────────────────────
# Derived from the real code paths:
#   reset:          00_core.admin_reset empties nations /
#                   scheduled_actions / tick_log and releases
#                   provinces.nation_id; 01_map.reset_ownership_log
#                   empties map_ownership_log; 02_bot.bot_reset empties
#                   bot_outbox; 04_orders.orders_reset empties orders.
#   player_delete:  PlayerService.delete_player removes the players row;
#                   NationService.delete removes its nations row and
#                   releases provinces; the registered player-delete
#                   hooks remove bot_consents + bot_outbox (02_bot),
#                   registry_vk_profiles (03_registry) and the player's
#                   orders (04_orders).
TABLE_COVERAGE: dict[str, object] = {
    # -- emptied by the world reset (asserted empty below) -----------
    "nations": "reset",
    "scheduled_actions": "reset",
    "tick_log": "reset",
    "map_ownership_log": "reset",
    "orders": "reset",
    "bot_outbox": "reset",
    # -- rows removed/released when one player is deleted -------------
    "players": "player_delete",
    "bot_consents": "player_delete",
    "registry_vk_profiles": "player_delete",
    # -- deliberately survive both -----------------------------------
    "provinces": (
        "kept",
        "map geography: nation_id is released, the row survives",
    ),
    "game_clock": (
        "kept",
        "singleton clock row is rewound to turn 0, never emptied",
    ),
    "bot_state": (
        "kept",
        "singleton digest marker is zeroed, never emptied",
    ),
    "bot_vk_events": (
        "kept",
        "inbound-event dedupe journal; a reset must not reprocess VK events",
    ),
    "admin_audit_log": (
        "kept",
        "admin journal — the audit trail survives reset and deletion",
    ),
    "admin_grants": (
        "kept",
        "admin rights survive reset; granted players are undeletable",
    ),
}

_UNCLASSIFIED: list[str] = []  # tables reported as unclassified


def test_every_metadata_table_is_classified():
    """The dictionary covers exactly ``Base.metadata`` — no more, no less."""
    actual = set(Base.metadata.tables)
    expected = set(TABLE_COVERAGE)

    missing = sorted(actual - expected)
    stale = sorted(expected - actual)

    assert not missing, (
        f"New table(s) not covered by the admin-table guard: {missing}. "
        "Decide its fate and extend the world reset, the player "
        "delete-preview/deletion, or TABLE_COVERAGE in "
        "test_admin_table_coverage.py — never leave a table "
        "unclassified."
    )
    assert not stale, (
        f"TABLE_COVERAGE names tables that no longer exist: {stale} — "
        "remove or update the entries."
    )
    assert _UNCLASSIFIED == [], (
        f"Unclassified tables remain: {_UNCLASSIFIED} — classify them "
        "in TABLE_COVERAGE with a derived reason."
    )


@pytest_asyncio.fixture
async def live_client(tmp_path, monkeypatch, mini_map_config):
    """The real app over its real lifespan on a migrated temporary
    database — the test_players_list.py live_client pattern, with the
    reset gate enabled."""
    if PG_TEST_URL is not None:
        _reset_pg_schema(PG_TEST_URL)
        db_url = _async_url(PG_TEST_URL)
    else:
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'admin.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("ADMIN_ALLOW_RESET", "true")
    monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_previews = AdminRegistry.get_player_preview_hooks()
    saved_overviews = AdminRegistry.get_overview_hooks()
    saved_player_infos = AdminRegistry.get_player_info_hooks()
    saved_province_infos = AdminRegistry.get_province_info_hooks()
    saved_handlers = {
        phase: list(handlers) for phase, handlers in TickOrchestrator._handlers.items()
    }
    saved_finalize = TickOrchestrator._finalize_callback
    saved_extensions = snapshot_extension_points()
    saved_map_service = map_service_module._instance

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    AdminRegistry._player_preview_hooks.clear()
    AdminRegistry._player_preview_hooks.update(saved_previews)
    AdminRegistry._overview_hooks.clear()
    AdminRegistry._overview_hooks.update(saved_overviews)
    AdminRegistry._player_info_hooks.clear()
    AdminRegistry._player_info_hooks.update(saved_player_infos)
    AdminRegistry._province_info_hooks.clear()
    AdminRegistry._province_info_hooks.update(saved_province_infos)
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved_handlers)
    TickOrchestrator._finalize_callback = saved_finalize
    restore_extension_points(saved_extensions)
    map_service_module._instance = saved_map_service


async def _auth_headers(client: AsyncClient, vk_user_id: int) -> dict:
    """Real login through /api/v1/auth/vk -> Authorization header."""
    response = await client.post(
        "/api/v1/auth/vk",
        json={
            "launch_params": make_launch_params(
                vk_user_id=vk_user_id, secret=TEST_VK_SECRET
            )
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _count(model) -> int:
    async with get_session_context() as session:
        return (
            await session.execute(select(func.count()).select_from(model))
        ).scalar_one()


@pytest.mark.asyncio
async def test_reset_empties_every_reset_table(live_client, monkeypatch):
    """Behavioural check: seed one row into every ``reset`` table, run
    the real ``POST /admin/state/reset`` and assert they are empty."""
    monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))
    headers = await _auth_headers(live_client, ADMIN_VK_ID)

    async with get_session_context() as session:
        player = PlayerFactory.build(vk_user_id=999001, nations=[])
        session.add(player)
        await session.flush()
        session.add(
            NationFactory.build(
                owner=player, provinces=[], scheduled_actions=[]
            )
        )
        # nation=None: the factory would otherwise build a nested
        # nation (and its nested owner) with random, CHECK-invalid rows.
        session.add(ScheduledActionFactory.build(nation=None))
        session.add(TickLogFactory.build())
        session.add(
            MapOwnershipLog(
                province_id=map_mini_node_ids()[0],
                turn_number=1,
                created_at=datetime.now(UTC),
            )
        )
        await make_order(session, player)
        await make_outbox_row(session, player)
        await session.commit()

    response = await live_client.post(
        "/api/v1/admin/state/reset",
        json={"confirm": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    reset_tables = {
        "nations": Nation,
        "scheduled_actions": ScheduledAction,
        "tick_log": TickLog,
        "map_ownership_log": MapOwnershipLog,
        "orders": Order,
        "bot_outbox": BotOutbox,
    }
    # The behavioural check covers exactly the tables the dictionary
    # marks "reset" — a table reclassified later moves out of both.
    assert set(reset_tables) == {
        name for name, kind in TABLE_COVERAGE.items() if kind == "reset"
    }
    leftovers = {
        name: await _count(model)
        for name, model in reset_tables.items()
        if await _count(model) > 0
    }
    assert leftovers == {}, (
        f"world reset left rows in tables marked 'reset': {leftovers}"
    )
