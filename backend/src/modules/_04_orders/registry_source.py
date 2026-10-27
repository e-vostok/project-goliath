"""
Registry table source ``orders`` of module 04_orders (Spec Appendix A).

Registered by ``register_orders_extensions()`` before
``startup_registry()`` (Spec D11) so the config check finds the source.
The source reads only ``OrderService.list_for_registry`` — a view with
no judge fields — and never writes (INV-O5, INV-O7). Row key ``o<N>``;
rows come newest first from the service.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import NationService
from modules._03_registry.cells import (
    cell_action_text,
    cell_datetime,
    cell_nation,
)
from modules._03_registry.registry import RegistryRow
from modules._03_registry.startup import get_core_config
from modules._04_orders.service import OrderService

# The value keys the source promises (Spec Appendix A) — a config column's
# ``source`` must name one of these (checked at startup, Spec 2.5).
ORDERS_PROVIDES = frozenset(
    {"number", "nation", "title", "submitted", "distributed", "verdict"}
)


def _aware(moment: datetime) -> datetime:
    """Naive datetimes are read as UTC (storage convention, as in cells)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


async def load_orders_rows(session: AsyncSession) -> list[RegistryRow]:
    """
    The ``orders`` source (Spec Appendix A).

    ``submitted``/``distributed``/``verdict`` are ``datetime`` cells in
    ``tick.tick_timezone``; a still-empty ``verdict`` cell of an order
    past its deadline carries ``mark = "overdue"``.
    """
    tz = get_core_config().tick.tick_timezone
    now = datetime.now(UTC)
    rows = await OrderService.list_for_registry(session)
    # The cell links to the nation subscreen only when the snapshot's
    # nation still exists — one batched existence check for the whole
    # table (INV-O7: nations are read only through the 00_core service).
    existing = await NationService.existing_ids(
        session, [row.nation_id for row in rows]
    )
    return [
        RegistryRow(
            key=f"o{row.number}",
            cells={
                "number": row.number,
                # The cell name and colour stay the SNAPSHOT (INV-O6);
                # only the link (and the tip) are live — a deleted
                # nation keeps its snapshot, plain, with id = null.
                "nation": cell_nation(
                    row.nation_short_name,
                    row.nation_color,
                    nation_id=(
                        row.nation_id if row.nation_id in existing else None
                    ),
                ),
                "title": cell_action_text(text=row.title, action=f"order:{row.number}"),
                "submitted": cell_datetime(row.submitted_at, tz),
                "distributed": cell_datetime(row.distributed_at, tz),
                "verdict": cell_datetime(
                    row.verdict_at,
                    tz,
                    mark=(
                        "overdue"
                        if row.verdict_at is None
                        and row.deadline_at is not None
                        and now > _aware(row.deadline_at)
                        else None
                    ),
                ),
            },
        )
        for row in rows
    ]
