"""
Tests for the player route of module 03_registry (Spec 5.6; INV-R2).

``GET /api/v1/registry/players/{number}`` returns the public card of
one player — the very cells the ``players`` table shows in row
``p<N>``. Real app + real in-memory DB; the session dependency is
overridden the same way the other suites do it — nothing else is
mocked (the ``request_wake`` spy only counts calls, it is not DB
state).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import modules._03_registry.sources as sources_module
from tests.fixtures.factories import make_vk_profile
from tests.modules._03_registry.conftest import (
    bearer_headers,
    seed_nation,
    seed_player,
)

PLAYERS_URL = "/api/v1/registry/players"
TABLES_URL = "/api/v1/registry/tables"


class TestPlayerRoute:
    """GET /api/v1/registry/players/{number} (Spec 5.6)."""

    async def test_ok_profile_and_nation(
        self, client, test_db_session, registry_started
    ):
        owner = await seed_player(test_db_session, 507001)
        viewer = await seed_player(test_db_session, 507002)
        nation = await seed_nation(
            test_db_session,
            owner,
            "Северная Конфедерация Вольных Городов",
            "#AA2201",
            created_turn=0,
            short_name="СКВГ",
            flag_id="flag_placeholder_1",
        )
        await make_vk_profile(
            test_db_session,
            owner,
            status="OK",
            first_name="Иван",
            last_name="Петров",
            photo_url="https://example.ru/a50.png",
        )

        resp = await client.get(f"{PLAYERS_URL}/1", headers=bearer_headers(viewer.id))

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        body = resp.json()
        assert set(body) == {
            "number",
            "person",
            "joined",
            "level",
            "judge_rating",
            "nation",
        }
        assert body["number"] == 1
        assert body["person"] == {
            "name": "Иван Петров",
            "avatar_url": "https://example.ru/a50.png",
            "is_fallback": False,
        }
        assert set(body["joined"]) == {"text", "key"}
        assert body["level"] == 1
        assert body["judge_rating"] == 0
        # ``name`` is the short name; ``id`` is the nation uuid —
        # nations are public by uuid already.
        assert body["nation"] == {
            "id": nation.id,
            "name": "СКВГ",
            "color": "#AA2201",
            "flag_url": "/assets/nations/flags/flag_placeholder_1.png",
        }

    async def test_unavailable_profile_keeps_last_good_name(
        self, client, test_db_session, registry_started
    ):
        player = await seed_player(test_db_session, 507101)
        viewer = await seed_player(test_db_session, 507102)
        await make_vk_profile(
            test_db_session,
            player,
            status="UNAVAILABLE",
            first_name="Иван",
            last_name="Петров",
            photo_url="https://example.ru/a50.png",
        )

        resp = await client.get(f"{PLAYERS_URL}/1", headers=bearer_headers(viewer.id))

        assert resp.status_code == 200
        body = resp.json()
        # The last good name stays; the avatar shows only for an OK
        # profile.
        assert body["person"] == {
            "name": "Иван Петров",
            "avatar_url": None,
            "is_fallback": False,
        }
        # A player without a nation gets a null field.
        assert body["nation"] is None

    async def test_no_profile_row_fallback(
        self, client, test_db_session, registry_started
    ):
        await seed_player(test_db_session, 507201)
        viewer = await seed_player(test_db_session, 507202)

        resp = await client.get(f"{PLAYERS_URL}/1", headers=bearer_headers(viewer.id))

        assert resp.status_code == 200
        assert resp.json()["person"] == {
            "name": "Игрок №1",
            "avatar_url": None,
            "is_fallback": True,
        }

    async def test_numbers_address_the_right_players(
        self, client, test_db_session, registry_started
    ):
        t0 = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
        p1 = await seed_player(test_db_session, 507301, created_at=t0)
        p2 = await seed_player(
            test_db_session, 507302, created_at=t0 + timedelta(hours=1)
        )
        await make_vk_profile(
            test_db_session,
            p1,
            status="OK",
            first_name="Первый",
            last_name="Игрок",
        )
        await make_vk_profile(
            test_db_session,
            p2,
            status="OK",
            first_name="Второй",
            last_name="Игрок",
        )
        headers = bearer_headers(p1.id)

        first = await client.get(f"{PLAYERS_URL}/1", headers=headers)
        second = await client.get(f"{PLAYERS_URL}/2", headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["number"] == 1
        assert first.json()["person"]["name"] == "Первый Игрок"
        assert second.json()["number"] == 2
        assert second.json()["person"]["name"] == "Второй Игрок"

    async def test_number_out_of_range_and_invalid(
        self, client, test_db_session, registry_started
    ):
        viewer = await seed_player(test_db_session, 507401)
        await seed_player(test_db_session, 507402)
        headers = bearer_headers(viewer.id)

        # A well-formed number beyond the player list — the domain 404.
        resp = await client.get(f"{PLAYERS_URL}/3", headers=headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == "REGISTRY_PLAYER_NOT_FOUND"
        assert body["detail"] == "Игрок №3 не найден"
        assert body["details"] == {"number": 3}

        # int/ge=1 path typing turns 0, negatives and non-integers into
        # the usual request-validation 422.
        for bad in ("0", "-1", "abc"):
            resp = await client.get(f"{PLAYERS_URL}/{bad}", headers=headers)
            assert resp.status_code == 422

    async def test_requires_token(self, client, registry_started):
        resp = await client.get(f"{PLAYERS_URL}/1")
        assert resp.status_code == 401

    async def test_route_agrees_with_table_row(
        self, client, test_db_session, registry_started
    ):
        owner = await seed_player(test_db_session, 507501)
        viewer = await seed_player(test_db_session, 507502)
        await seed_nation(
            test_db_session, owner, "Согласие", "#334455", short_name="СГЛ"
        )
        await make_vk_profile(
            test_db_session,
            owner,
            status="OK",
            first_name="Совпадающий",
            last_name="Игрок",
            photo_url="https://example.ru/p50.png",
        )
        headers = bearer_headers(viewer.id)

        table = await client.get(f"{TABLES_URL}/players", headers=headers)
        row = next(r for r in table.json()["rows"] if r["key"] == "p1")
        resp = await client.get(f"{PLAYERS_URL}/1", headers=headers)

        # The route returns the very cells of the table row (Spec 5.6).
        cells = row["cells"]
        body = resp.json()
        assert body["number"] == cells["number"]
        assert body["person"] == cells["player"]
        assert body["joined"] == cells["joined"]
        assert body["level"] == cells["level"]
        assert body["judge_rating"] == cells["judge_rating"]
        assert body["nation"] == cells["nation"]

    async def test_no_player_identifiers_in_body(
        self, client, test_db_session, registry_started
    ):
        """INV-R2: no vk_user_id and no player uuid in the body."""
        target = await seed_player(test_db_session, 507601)
        viewer = await seed_player(test_db_session, 507602)
        await seed_nation(
            test_db_session, target, "Приват", "#445566", short_name="ПРВ"
        )

        resp = await client.get(f"{PLAYERS_URL}/1", headers=bearer_headers(viewer.id))

        assert resp.status_code == 200
        text = resp.text
        for forbidden in (
            target.id,
            viewer.id,
            str(target.vk_user_id),
            str(viewer.vk_user_id),
            "vk_user_id",
            "player_id",
        ):
            assert forbidden not in text

    async def test_wake_only_for_due_or_missing_profile(
        self, client, test_db_session, registry_started, monkeypatch
    ):
        """The Spec 2.4 wake rule narrowed to the one player: no profile
        row rings the bell; a deferred retry does not."""
        calls = 0

        def _spy():
            nonlocal calls
            calls += 1

        monkeypatch.setattr(sources_module, "request_wake", _spy)

        deferred = await seed_player(test_db_session, 507701)
        await seed_player(test_db_session, 507702)
        await make_vk_profile(
            test_db_session,
            deferred,
            status="UNAVAILABLE",
            next_attempt_at=datetime.now(UTC) + timedelta(hours=1),
        )
        headers = bearer_headers(deferred.id)

        # Player №1: a profile row with a deferred retry — no wake.
        resp = await client.get(f"{PLAYERS_URL}/1", headers=headers)
        assert resp.status_code == 200
        assert calls == 0

        # Player №2: no profile row — the bell rings once.
        resp = await client.get(f"{PLAYERS_URL}/2", headers=headers)
        assert resp.status_code == 200
        assert calls == 1
