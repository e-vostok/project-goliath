"""
Table assembly of module 03_registry (Spec 3.1).

``build_table`` turns a configured table into rows: find the table in
the config, call its registered source, check every cell of every
configured column against the Spec 3.6 shape (a violation is
``REGISTRY_PROVIDER_FAILED`` — the log names table and column, never
values), apply the default sort (empty values last, stable either way),
cap at ``limits.max_rows_per_table`` (INV-R4) and emit only the keys
the configured columns list, addressed by column id (the client never
sees ``source`` keys — Spec 5.1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from modules._03_registry.cells import cell_matches
from modules._03_registry.config_schema import ColumnConfig
from modules._03_registry.errors import (
    RegistryDomainError,
    RegistryProviderError,
    RegistryTableNotFoundError,
)
from modules._03_registry.registry import Cell, RegistryRow, get_table_source

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltTable:
    """The assembled rows response for one table (Spec 5.2)."""

    table_id: str
    total: int
    truncated: bool
    generated_at: datetime
    # Cells are keyed by column id; only configured keys are present.
    rows: list[RegistryRow]


def _sort_value(column_type: str, cell: Cell):
    """
    The comparison key of a cell for the default sort (Spec 3.7):
    a number for index/integer/gauge, ``key`` for date, ``name`` for
    person/nation, the string itself for text. ``None`` for empty cells.
    String keys compare case-insensitively, like the client's collator.
    """
    if cell is None:
        return None
    if column_type in ("index", "integer", "gauge"):
        return cell
    if column_type == "text":
        return cell.casefold()
    if column_type == "action_text":
        return cell["text"].casefold()
    if column_type == "date":
        return cell["key"]
    if column_type == "datetime":
        return cell["key"]
    if column_type in ("person", "nation"):
        return cell["name"].casefold()
    return None


def _default_sort(
    rows: list[RegistryRow],
    column: ColumnConfig,
    direction: str,
) -> list[RegistryRow]:
    """
    Order rows by ``column`` (Spec 3.1 step 4): empty values always last
    in both directions, the sort is stable — equal keys keep the
    source's order.
    """
    keyed = [
        (i, _sort_value(column.type, row.cells.get(column.source)), row)
        for i, row in enumerate(rows)
    ]
    filled = [item for item in keyed if item[1] is not None]
    empty = [item for item in keyed if item[1] is None]
    filled.sort(key=lambda item: item[1], reverse=(direction == "desc"))
    return [row for _, _, row in filled + empty]


async def build_table(
    session: AsyncSession, table_id: str
) -> BuiltTable:
    """
    Build the rows of one configured table (Spec 3.1).

    Raises:
        RegistryTableNotFoundError: ``table_id`` is not in the config.
        RegistryProviderError: the source failed or returned a cell that
            violates its column's Spec 3.6 shape (or omitted a key).
    """
    # Local import: startup.py does not import this module, so the holder
    # lives there (as get_bot_config in 02_bot).
    from modules._03_registry.startup import get_registry_config

    config = get_registry_config()
    try:
        table = config.table(table_id)
    except KeyError:
        raise RegistryTableNotFoundError(table_id)

    source = get_table_source(table.source)
    if source is None:
        # Startup validated this (Spec 2.5 step 3); reaching it at
        # request time means the registry was reset mid-process.
        logger.error(
            "registry table '%s' has no registered source", table.id
        )
        raise RegistryProviderError(table_id)

    try:
        rows = await source.load(session)
    except RegistryDomainError:
        raise
    except Exception:
        logger.exception(
            "registry source failed: table=%s", table.id
        )
        raise RegistryProviderError(table_id)

    for row in rows:
        for column in table.columns:
            if column.source not in row.cells or not cell_matches(
                column.type, row.cells[column.source]
            ):
                logger.error(
                    "registry provider returned a bad cell: table=%s "
                    "column=%s",
                    table.id,
                    column.id,
                )
                raise RegistryProviderError(table_id, column.id)

    sort_column = next(
        c for c in table.columns if c.id == table.default_sort.column
    )
    rows = _default_sort(rows, sort_column, table.default_sort.direction)

    total = len(rows)
    cap = config.limits.max_rows_per_table
    truncated = total > cap
    rows = rows[:cap]

    return BuiltTable(
        table_id=table.id,
        total=total,
        truncated=truncated,
        generated_at=datetime.now(timezone.utc),
        rows=[
            RegistryRow(
                key=row.key,
                cells={
                    column.id: row.cells[column.source]
                    for column in table.columns
                },
            )
            for row in rows
        ],
    )
