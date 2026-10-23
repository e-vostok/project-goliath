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
from modules._00_core.config_schema import CoreConfig
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


async def _submit_one(session, vk_user_id: int = 770301):
    player, nation = await seed_author(session, vk_user_id, nation_name="Северная Лига")
    await OrderService.submit(
        session,
        player_id=player.id,
        client_request_id=str(uuid.uuid4()),
        title=VALID_TITLE,
        summary=VALID_SUMMARY,
        article_url=VALID_URL,
    )
    return nation


class TestOrdersSource:
    """The row shape of the ``orders`` Registry source (Appendix A)."""

    async def test_row_shape_has_no_judge_fields(self, test_db_session, orders_started):
        register_orders_extensions()
        startup_registry()
        nation = await _submit_one(test_db_session)

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
        # The order stores an identity snapshot — `id` is None: the
        # cell shows the short name and flag but cannot open the
        # nation subscreen.
        assert row.cells["nation"] == {
            "id": None,
            "name": nation.short_name,
            "color": "#336699",
            "flag_url": "/assets/nations/flags/flag_placeholder_1.png",
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
        empty = {"date": None, "time": None, "key": None, "day": None, "mark": None}
        assert row.cells["distributed"] == empty
        assert row.cells["verdict"] == empty

        # INV-O5: nothing in the row identifies the judge or a VK user.
        text = json.dumps(row.cells, ensure_ascii=False)
        for needle in ("judge", "vk_user", "player_id"):
            assert needle not in text

    async def test_nation_cell_matches_select_options(
        self, test_db_session, orders_started
    ):
        """Spec 3.7: the orders ``select_or_contains`` dropdown is built
        from the nations-table ``nation`` cells — the short name the
        orders ``nation`` cell shows must appear among them."""
        register_orders_extensions()
        startup_registry()
        nation = await _submit_one(test_db_session)

        orders_table = await build_table(test_db_session, "orders")
        nations_table = await build_table(test_db_session, "nations")

        option_names = [
            row.cells["name"]["name"] for row in nations_table.rows
        ]
        cell = orders_table.rows[0].cells["nation"]
        assert cell["name"] == nation.short_name
        assert cell["name"] in option_names

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


class TestCoreConfigInjection:
    """The ``orders`` source uses the CoreConfig captured by
    ``startup_registry`` — a table request must never re-open
    ``00_core.yaml`` (same guard as the built-in sources)."""

    async def test_source_uses_injected_config_without_disk_read(
        self, test_db_session, orders_started, monkeypatch
    ):
        core_config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        monkeypatch.setattr(
            CoreConfig,
            "from_yaml",
            classmethod(
                lambda cls, path: pytest.fail(
                    "CoreConfig.from_yaml called during a table request"
                )
            ),
        )
        register_orders_extensions()
        startup_registry(core_config=core_config)
        await _submit_one(test_db_session)

        built = await build_table(test_db_session, "orders")

        assert built.total == 1
        assert built.rows[0].key == "o1"
        assert built.rows[0].cells["submitted"]["date"] is not None


class TestStartupCheck:
    """Spec D11 + 03_registry 2.5: a config source nobody registered
    must abort the boot."""

    def test_startup_aborts_on_unknown_registry_source(self, orders_isolation):
        # The real config lists the ``orders`` table; with no
        # register_orders_extensions() call the source is unknown and
        # startup_registry() must raise before serving.
        registry_module.clear_registry()
        with pytest.raises(RegistryConfigError) as exc_info:
            startup_registry()
        assert "orders" in str(exc_info.value)
