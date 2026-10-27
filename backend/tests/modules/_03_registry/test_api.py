"""
Tests for the HTTP API of module 03_registry (Spec 5.1, 5.2; INV-R2).

Real app + real in-memory DB; the session dependency is overridden the
same way the other suites do it — nothing else is mocked.
"""

from __future__ import annotations

from tests.modules._03_registry.conftest import (
    bearer_headers,
    seed_nation,
    seed_player,
)

TABLES_URL = "/api/v1/registry/tables"


def _walk_no_source_key(node):
    """Assert no ``source`` key exists anywhere in the JSON tree."""
    if isinstance(node, dict):
        assert "source" not in node
        for value in node.values():
            _walk_no_source_key(value)
    elif isinstance(node, list):
        for value in node:
            _walk_no_source_key(value)


class TestTablesEndpoint:
    """GET /api/v1/registry/tables (Spec 5.1)."""

    async def test_tables_description_for_nationless_player(
        self, client, test_db_session, registry_started
    ):
        player = await seed_player(test_db_session, 505001)

        resp = await client.get(TABLES_URL, headers=bearer_headers(player.id))

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"
        body = resp.json()
        assert body["layout"] == {"tabs_position": "top"}
        assert [t["id"] for t in body["tables"]] == [
            "players",
            "nations",
            "orders",
        ]
        orders = body["tables"][2]
        assert orders["icon"] == "orders"
        assert orders["default_sort"] == {
            "column": "number",
            "direction": "desc",
        }
        order_columns = {c["id"]: c for c in orders["columns"]}
        assert order_columns["title"]["type"] == "action_text"
        # 0.10.0 unit 13: approved mockups show the stage titles as
        # text — no header icons in the shipped config.
        assert order_columns["submitted"]["header_icon"] is None
        assert order_columns["submitted"]["title"] == "Подача"
        assert order_columns["verdict"]["filters"] == [
            "date_range",
            "presence",
        ]
        players = body["tables"][0]
        assert players["title"] == "Игроки"
        assert players["default_sort"] == {
            "column": "number",
            "direction": "asc",
        }
        columns = {c["id"]: c for c in players["columns"]}
        assert columns["number"] == {
            "id": "number",
            "title": "№",
            "type": "index",
            "width_px": 48,
            "sortable": True,
            "filters": [],
            "filter_label": None,
            "header_icon": None,
            "searchable": False,
            "stub": False,
            "scale_min": None,
            "scale_max": None,
        }
        assert columns["judge_rating"]["scale_min"] == -100
        assert columns["judge_rating"]["scale_max"] == 100
        # Shortened titles (0.10.0 unit 6b).
        assert columns["judge_rating"]["title"] == "Рейтинг"
        assert columns["joined"]["title"] == "Регистрация"
        # Nations: no separate «flag» column; «name» is a nation cell
        # with the select_or_contains filter (Spec 3.3, 3.7).
        nations = body["tables"][1]
        n_columns = {c["id"]: c for c in nations["columns"]}
        assert "flag" not in n_columns
        assert n_columns["name"]["type"] == "nation"
        assert n_columns["name"]["filters"] == ["select_or_contains"]
        assert n_columns["name"]["searchable"] is True
        assert n_columns["name"]["sortable"] is True
        # Spec 5.1: source fields are never sent to the client.
        _walk_no_source_key(body)

    async def test_tables_requires_token(self, client, registry_started):
        resp = await client.get(TABLES_URL)
        assert resp.status_code == 401


class TestRowsEndpoint:
    """GET /api/v1/registry/tables/{table_id} (Spec 5.2)."""

    async def test_players_rows_for_nationless_player(
        self, client, test_db_session, registry_started
    ):
        player = await seed_player(test_db_session, 505101)

        resp = await client.get(
            f"{TABLES_URL}/players", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        body = resp.json()
        assert body["table_id"] == "players"
        assert body["total"] == 1
        assert body["truncated"] is False
        assert body["generated_at"].endswith("Z")
        row = body["rows"][0]
        assert row["key"] == "p1"
        assert set(row["cells"]) == {
            "number",
            "player",
            "joined",
            "level",
            "judge_rating",
            "nation",
        }
        assert row["cells"]["player"]["name"] == "Игрок №1"
        assert row["cells"]["nation"] is None

    async def test_nations_rows_empty_table(
        self, client, test_db_session, registry_started
    ):
        player = await seed_player(test_db_session, 505102)

        resp = await client.get(
            f"{TABLES_URL}/nations", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["table_id"] == "nations"
        assert body["total"] == 0
        assert body["rows"] == []

    async def test_unknown_table_404(self, client, test_db_session, registry_started):
        player = await seed_player(test_db_session, 505103)

        resp = await client.get(
            f"{TABLES_URL}/ghost", headers=bearer_headers(player.id)
        )

        assert resp.status_code == 404
        assert resp.json()["code"] == "REGISTRY_TABLE_NOT_FOUND"

    async def test_rows_requires_token(self, client, registry_started):
        resp = await client.get(f"{TABLES_URL}/players")
        assert resp.status_code == 401

    async def test_no_player_identifiers_anywhere(
        self, client, test_db_session, registry_started
    ):
        """INV-R2: no vk_user_id and no player uuid in either body."""
        me = await seed_player(test_db_session, 505201)
        other = await seed_player(
            test_db_session,
            505202,
        )

        for url in (TABLES_URL, f"{TABLES_URL}/players", f"{TABLES_URL}/nations"):
            resp = await client.get(url, headers=bearer_headers(me.id))
            assert resp.status_code == 200
            text = resp.text
            for forbidden in (
                me.id,
                other.id,
                str(me.vk_user_id),
                str(other.vk_user_id),
                "vk_user_id",
                "player_id",
            ):
                assert forbidden not in text


class TestNationCellsAcrossTables:
    """Spec 1.4/1.6 (3.2, 3.3, 3.7): the nations-table «name» column
    carries the same ``nation`` cell the players table gives the owner
    nation — short name + colour + the nation id that opens the
    subscreen; ``flag_url`` stays None until the upload lands."""

    async def test_nation_cells_in_nations_and_players_tables(
        self, client, test_db_session, registry_started
    ):
        owner_modern = await seed_player(test_db_session, 506001)
        owner_flagless = await seed_player(test_db_session, 506002)
        viewer = await seed_player(test_db_session, 506003)
        modern = await seed_nation(
            test_db_session,
            owner_modern,
            "Северная Конфедерация Вольных Городов",
            "#AA2201",
            created_turn=0,
            short_name="СКВГ",
        )
        flagless = await seed_nation(
            test_db_session,
            owner_flagless,
            "Древнее Княжество Полное",
            "#AA2202",
            created_turn=1,
            short_name="ДКП",
        )
        headers = bearer_headers(viewer.id)

        resp = await client.get(f"{TABLES_URL}/nations", headers=headers)
        assert resp.status_code == 200
        n_rows = resp.json()["rows"]
        nations_by_key = {row["key"]: row["cells"] for row in n_rows}
        assert nations_by_key[modern.id]["name"] == {
            "id": modern.id,
            "name": "СКВГ",
            "color": "#AA2201",
            "flag_url": None,
        }
        assert nations_by_key[flagless.id]["name"] == {
            "id": flagless.id,
            "name": "ДКП",
            "color": "#AA2202",
            "flag_url": None,
        }
        # No flag cells remain in the row (Spec 1.6: no «flag» column).
        assert "flag" not in nations_by_key[modern.id]
        assert "flag" not in nations_by_key[flagless.id]

        resp = await client.get(f"{TABLES_URL}/players", headers=headers)
        assert resp.status_code == 200
        p_rows = {row["key"]: row["cells"] for row in resp.json()["rows"]}
        assert p_rows["p1"]["nation"] == {
            "id": modern.id,
            "name": "СКВГ",
            "color": "#AA2201",
            "flag_url": None,
        }
        assert p_rows["p2"]["nation"] == {
            "id": flagless.id,
            "name": "ДКП",
            "color": "#AA2202",
            "flag_url": None,
        }
        assert p_rows["p3"]["nation"] is None

        # Spec 3.7: the ``select_or_contains`` dropdown is built from the
        # nations-table ``nation`` cells of the ``name`` column — their
        # names must equal the ``nation`` cell names the players table
        # shows.
        option_names = [row["cells"]["name"]["name"] for row in n_rows]
        assert option_names == [
            p_rows["p1"]["nation"]["name"],
            p_rows["p2"]["nation"]["name"],
        ]
