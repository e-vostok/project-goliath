"""
Registry-source tests of module 04_orders (Spec Appendix A, D11).

The ``orders`` table source is exercised through the real
``build_table`` — the shipped ``configs/03_registry.yaml`` drives the
column mapping — and the boot-order contract (extensions registered
before ``startup_registry()``) is checked against the real config.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest

import modules._03_registry.registry as registry_module
from modules._03_registry.errors import RegistryConfigError
from modules._03_registry.service import build_table
from modules._03_registry.startup import startup_registry
from modules._04_orders.service import OrderService
from modules._04_orders.startup import register_orders_extensions
from tests.fixtures.factories import make_order, utcnow
from tests.modules._04_orders.conftest import seed_author, seed_judge

VALID_TITLE = "Приказ об обороне"
VALID_SUMMARY = "Удержать переправу до подхода резервов."
VALID_URL = "https://vk.com/@defence-order"


async def _submit_one(session, vk_user_id: int = 770301) -> None:
    player, _ = await seed_author(
        session, vk_user_id, nation_name="Северная Лига"
    )
    await OrderService.submit(
        session,
        player_id=player.id,
        client_request_id=str(uuid.uuid4()),
        title=VALID_TITLE,
        summary=VALID_SUMMARY,
        article_url=VALID_URL,
    )


class TestOrdersSource:
    """The row shape of the ``orders`` Registry source (Appendix A)."""

    async def test_row_shape_has_no_judge_fields(
        self, test_db_session, orders_started
    ):
        register_orders_extensions()
        startup_registry()
        await _submit_one(test_db_session)

        built = await build_table(test_db_session, "orders")

        assert built.table_id == "orders"
        assert built.total == 1
        row = built.rows[0]
        assert row.key == "o1"
        assert set(row.cells) == {
            "number",
            "nation",
            "title",
            "submitted",
            "distributed",
            "verdict",
        }
        assert row.cells["number"] == 1
        assert row.cells["nation"] == {
            "name": "Северная Лига",
            "color": "#336699",
            "flag_url": None,
        }
        assert row.cells["title"] == {
            "text": VALID_TITLE,
            "action": "order:1",
        }
        submitted = row.cells["submitted"]
        assert isinstance(submitted["date"], str)
        assert isinstance(submitted["time"], str)
        assert isinstance(submitted["key"], int)
        assert isinstance(submitted["day"], int)
        assert submitted["mark"] is None
        empty = {"date": None, "time": None, "key": None,
                 "day": None, "mark": None}
        assert row.cells["distributed"] == empty
        assert row.cells["verdict"] == empty

        # INV-O5: nothing in the row identifies the judge or a VK user.
        text = json.dumps(row.cells, ensure_ascii=False)
        for needle in ("judge", "vk_user", "player_id"):
            assert needle not in text

    async def test_verdict_cell_fills_and_overdue_mark_clears(
        self, test_db_session, orders_started
    ):
        """Appendix A: an overdue order's empty ``verdict`` cell
        carries ``mark = "overdue"``; once the judge writes the
        verdict the cell is a real datetime and the mark is gone."""
        register_orders_extensions()
        startup_registry()
        author, nation = await seed_author(test_db_session, 770311)
        judge = await seed_judge(test_db_session, 770312, nation=True)
        # Submitted 80 h ago: the factory's +72 h deadline already
        # passed — the order is overdue until the verdict lands.
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            submitted_at=utcnow() - timedelta(hours=80),
        )

        built = await build_table(test_db_session, "orders")
        assert built.rows[0].cells["verdict"] == {
            "date": None,
            "time": None,
            "key": None,
            "day": None,
            "mark": "overdue",
        }

        await OrderService.write_verdict(
            test_db_session,
            player_id=judge.id,
            number=order.number,
            title="Вердикт по приказу",
            summary="Приказ рассмотрен и принят к исполнению.",
            article_url="https://vk.com/@verdict-one",
        )

        built = await build_table(test_db_session, "orders")
        cell = built.rows[0].cells["verdict"]
        assert cell["date"] is not None
        assert cell["time"] is not None
        assert cell["key"] is not None
        assert cell["day"] is not None
        assert cell["mark"] is None


class TestStartupCheck:
    """Spec D11 + 03_registry 2.5: a config source nobody registered
    must abort the boot."""

    def test_startup_aborts_on_unknown_registry_source(
        self, orders_isolation
    ):
        # The real config lists the ``orders`` table; with no
        # register_orders_extensions() call the source is unknown and
        # startup_registry() must raise before serving.
        registry_module.clear_registry()
        with pytest.raises(RegistryConfigError) as exc_info:
            startup_registry()
        assert "orders" in str(exc_info.value)
