"""
Tests for the HTTP API of module 03_registry (Spec 5.1, 5.2; INV-R2).

Real app + real in-memory DB; the session dependency is overridden the
same way the other suites do it — nothing else is mocked.
"""

from __future__ import annotations

from tests.modules._03_registry.conftest import bearer_headers, seed_player

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

        resp = await client.get(
            TABLES_URL, headers=bearer_headers(player.id)
        )

        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache"
        body = resp.json()
        assert body["layout"] == {"tabs_position": "top"}
        assert [t["id"] for t in body["tables"]] == ["players", "nations"]
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
            "width_px": 64,
            "sortable": True,
            "filters": [],
            "filter_label": None,
            "searchable": False,
            "stub": False,
            "scale_min": None,
            "scale_max": None,
        }
        assert columns["judge_rating"]["scale_min"] == -100
        assert columns["judge_rating"]["scale_max"] == 100
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

    async def test_unknown_table_404(
        self, client, test_db_session, registry_started
    ):
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
            test_db_session, 505202,
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
