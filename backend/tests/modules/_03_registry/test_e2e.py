"""
End-to-end tests of module 03_registry (Issue 5, Spec Appendix T).

Each scenario drives the whole stack: the real HTTP app with real
issued JWTs, the real in-memory DB through the shared fixtures, the
real ``TickOrchestrator.run_tick`` advancing the turn and the real
profile-worker ``run_cycle``. Only the VK boundary is faked
(``FakeVk`` on ``httpx.MockTransport`` — Anti-Mock Guard); nothing
else is mocked.

Scenario A — a nation founded on turn 0, the tick, a second nation on
turn 1, a third player without a nation; then the first nation is
deleted and the table renumbers.
Scenario B — one ``run_cycle`` over ``FakeVk``: an ``OK`` profile
shows the real name and avatar, a ``deactivated`` one keeps the
fallback «Игрок №N», and the workers' bell is not rung again while
every profile row is fresh.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from core.tick.orchestrator import TickOrchestrator, TickOutcome
from modules._00_core.calendar import compute_game_date
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import GameClock, Player
from modules._00_core.tick_handler import register_tick_handlers
from modules._03_registry.dates import game_date_text
from modules._03_registry.profile_worker import install_wake_event, run_cycle
from modules._03_registry.vk_profiles import VkProfilesClient
from tests.fixtures.fake_vk import FakeVk
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province
from tests.modules._03_registry.conftest import bearer_headers, seed_player

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

TABLES_URL = "/api/v1/registry/tables"
NATIONS_URL = "/api/v1/nations"
NATIONS_ME_URL = "/api/v1/nations/me"

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def tick_handlers():
    """The real finalize callback on an otherwise empty handler set."""
    TickOrchestrator.clear_handlers()
    register_tick_handlers()
    yield
    TickOrchestrator.clear_handlers()


async def _seed_clock(session, current_turn: int = 0) -> GameClock:
    """The game_clock singleton required by ``run_tick``."""
    clock = GameClock(
        id=1,
        current_turn=current_turn,
        last_tick_at=None,
        next_tick_at=datetime.now(timezone.utc),
    )
    session.add(clock)
    await session.flush()
    return clock


def _nation_body(name: str, color: str, province_ids: list[int]) -> dict:
    return {
        "name": name,
        "color_hex": color,
        "province_ids": province_ids,
        **VALID_PROFILE,
        # INV-11: each nation carries its own short name.
        "short_name": name[:16],
    }


def _assert_no_identifiers(text: str, players: list[Player]) -> None:
    """INV-R2: no ``vk_user_id`` and no player/owner uuid anywhere."""
    for player in players:
        assert str(player.vk_user_id) not in text
        assert player.id not in text
    assert "vk_user_id" not in text
    assert "player_id" not in text


class TestScenarioA:
    """Founding across a real tick, both tables, then a deletion."""

    async def test_tables_across_tick_and_deletion(
        self, client, test_db_session, registry_started, tick_handlers
    ):
        players = [
            await seed_player(
                test_db_session,
                9300001 + i,
                created_at=NOW + timedelta(hours=i),
            )
            for i in range(3)
        ]
        for province_id in range(1001, 1011):
            await make_land_province(test_db_session, id=province_id)
        await _seed_clock(test_db_session)
        await test_db_session.commit()

        # Turn 0: player 1 founds a five-province nation.
        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(players[0].id),
            json=_nation_body(
                "Северная Марка",
                "#AA1111",
                [1001, 1002, 1003, 1004, 1005],
            ),
        )
        assert resp.status_code == 201
        nation1_id = resp.json()["id"]

        # The real tick advances the game to turn 1.
        outcome = await TickOrchestrator.run_tick(test_db_session)
        assert outcome is TickOutcome.EXECUTED

        # Turn 1: player 2 founds a five-province nation.
        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(players[1].id),
            json=_nation_body(
                "Ладожский Союз",
                "#22BB33",
                [1006, 1007, 1008, 1009, 1010],
            ),
        )
        assert resp.status_code == 201
        nation2_id = resp.json()["id"]

        # Nations: both rows in numbering order, dates by creation turn.
        resp = await client.get(
            f"{TABLES_URL}/nations",
            headers=bearer_headers(players[2].id),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["table_id"] == "nations"
        assert body["total"] == 2
        assert body["truncated"] is False
        n1, n2 = body["rows"]
        assert n1["key"] == nation1_id
        assert n1["cells"]["number"] == 1
        assert n1["cells"]["name"] == "Северная Марка"
        assert n1["cells"]["flag"] == {
            "color": "#AA1111",
            "image_url": None,
        }
        assert n1["cells"]["formed"] == {
            "text": game_date_text(compute_game_date(0, CORE_CONFIG)),
            "key": 0,
        }
        assert n1["cells"]["provinces"] == 5
        assert n2["key"] == nation2_id
        assert n2["cells"]["number"] == 2
        assert n2["cells"]["name"] == "Ладожский Союз"
        assert n2["cells"]["formed"] == {
            "text": game_date_text(compute_game_date(1, CORE_CONFIG)),
            "key": 1,
        }
        assert n2["cells"]["provinces"] == 5
        _assert_no_identifiers(resp.text, players)

        # Players: the founders carry their nation, player 3 has none.
        resp = await client.get(
            f"{TABLES_URL}/players",
            headers=bearer_headers(players[2].id),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        p_rows = body["rows"]
        assert [row["key"] for row in p_rows] == ["p1", "p2", "p3"]
        assert [row["cells"]["number"] for row in p_rows] == [1, 2, 3]
        assert p_rows[0]["cells"]["player"]["name"] == "Игрок №1"
        assert p_rows[0]["cells"]["nation"] == {
            "name": "Северная Марка",
            "color": "#AA1111",
            "flag_url": None,
        }
        assert p_rows[1]["cells"]["nation"] == {
            "name": "Ладожский Союз",
            "color": "#22BB33",
            "flag_url": None,
        }
        assert p_rows[2]["cells"]["nation"] is None
        _assert_no_identifiers(resp.text, players)

        resp = await client.get(TABLES_URL, headers=bearer_headers(players[2].id))
        assert resp.status_code == 200
        _assert_no_identifiers(resp.text, players)

        # Player 1 deletes their nation through the real endpoint.
        resp = await client.request(
            "DELETE",
            NATIONS_ME_URL,
            headers=bearer_headers(players[0].id),
            json={"confirm": True},
        )
        assert resp.status_code == 204

        # The nations table renumbers; the players table loses the cell.
        resp = await client.get(
            f"{TABLES_URL}/nations",
            headers=bearer_headers(players[2].id),
        )
        body = resp.json()
        assert body["total"] == 1
        (n2,) = body["rows"]
        assert n2["key"] == nation2_id
        assert n2["cells"]["number"] == 1
        assert n2["cells"]["name"] == "Ладожский Союз"
        assert n2["cells"]["formed"]["key"] == 1
        assert n2["cells"]["provinces"] == 5
        _assert_no_identifiers(resp.text, players)

        resp = await client.get(
            f"{TABLES_URL}/players",
            headers=bearer_headers(players[2].id),
        )
        p_rows = resp.json()["rows"]
        assert [row["key"] for row in p_rows] == ["p1", "p2", "p3"]
        assert p_rows[0]["cells"]["nation"] is None
        assert p_rows[1]["cells"]["nation"] == {
            "name": "Ладожский Союз",
            "color": "#22BB33",
            "flag_url": None,
        }
        assert p_rows[2]["cells"]["nation"] is None
        _assert_no_identifiers(resp.text, players)


class TestScenarioB:
    """One real ``run_cycle`` over ``FakeVk`` end to end."""

    async def test_cycle_fills_names_and_silences_bell(
        self, client, test_db_session, session_factory, registry_started
    ):
        profiles = registry_started.profiles
        p_ok = await seed_player(test_db_session, 9400001, created_at=NOW)
        p_dead = await seed_player(
            test_db_session,
            9400002,
            created_at=NOW + timedelta(hours=1),
        )
        await test_db_session.commit()

        bell = asyncio.Event()
        install_wake_event(bell)

        # Before any fetch: fallback names, and the missing profile rows
        # ring the worker's bell (Spec 2.4).
        resp = await client.get(
            f"{TABLES_URL}/players", headers=bearer_headers(p_ok.id)
        )
        assert resp.status_code == 200
        rows = resp.json()["rows"]
        assert [row["cells"]["player"]["name"] for row in rows] == [
            "Игрок №1",
            "Игрок №2",
        ]
        assert bell.is_set()
        bell.clear()

        fake = FakeVk()
        fake.respond_users_get(
            [
                {
                    "id": 9400001,
                    "first_name": "Иван",
                    "last_name": "Петров",
                    "photo_50": "https://sun9-west.userapi.com/a.png",
                },
                {"id": 9400002, "deactivated": "banned"},
            ]
        )
        vk_client = VkProfilesClient(profiles, "test-token", transport=fake.transport)
        await test_db_session.commit()
        await run_cycle(
            session_factory,
            vk_client,
            profiles,
            datetime.now(timezone.utc),
        )
        await vk_client.aclose()

        resp = await client.get(
            f"{TABLES_URL}/players", headers=bearer_headers(p_ok.id)
        )
        assert resp.status_code == 200
        rows = resp.json()["rows"]
        assert rows[0]["cells"]["player"] == {
            "name": "Иван Петров",
            "avatar_url": "https://sun9-west.userapi.com/a.png",
            "is_fallback": False,
        }
        assert rows[1]["cells"]["player"] == {
            "name": "Игрок №2",
            "avatar_url": None,
            "is_fallback": True,
        }
        # Every row is fresh now — the bell stays silent.
        assert not bell.is_set()
        assert len(fake.users_get_requests()) == 1
        _assert_no_identifiers(resp.text, [p_ok, p_dead])

        resp = await client.get(
            f"{TABLES_URL}/nations", headers=bearer_headers(p_ok.id)
        )
        assert resp.status_code == 200
        _assert_no_identifiers(resp.text, [p_ok, p_dead])

        resp = await client.get(TABLES_URL, headers=bearer_headers(p_ok.id))
        assert resp.status_code == 200
        _assert_no_identifiers(resp.text, [p_ok, p_dead])
