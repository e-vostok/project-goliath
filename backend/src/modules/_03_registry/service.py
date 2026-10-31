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
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import PlayerService
from modules._03_registry.cells import cell_matches
from modules._03_registry.config_schema import ColumnConfig
from modules._03_registry.errors import (
    RegistryDomainError,
    RegistryProviderError,
    RegistryTableNotFoundError,
)
from modules._03_registry.models import (
    RegistryNumberCounter,
    RegistryPlayerNumber,
    RegistryVkProfile,
)
from modules._03_registry.registry import Cell, RegistryRow, get_table_source

logger = logging.getLogger(__name__)

# PostgreSQL advisory-lock key serializing number issuing across every
# process sharing the database ('REGNUM' as ASCII hex). Must fit
# bigint; no-op dialects skip it. Differs from the other modules' keys
# (00_core NATIONS, 04_orders ORDERS) — each lock guards its own data.
REGISTRY_NUMBERS_ADVISORY_LOCK_KEY = 0x5245474E554D


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


async def build_table(session: AsyncSession, table_id: str) -> BuiltTable:
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
        raise RegistryTableNotFoundError(table_id) from None

    source = get_table_source(table.source)
    if source is None:
        # Startup validated this (Spec 2.5 step 3); reaching it at
        # request time means the registry was reset mid-process.
        logger.error("registry table '%s' has no registered source", table.id)
        raise RegistryProviderError(table_id) from None

    try:
        rows = await source.load(session)
    except RegistryDomainError:
        raise
    except Exception:
        logger.exception("registry source failed: table=%s", table.id)
        raise RegistryProviderError(table_id) from None

    for row in rows:
        for column in table.columns:
            if column.source not in row.cells or not cell_matches(
                column.type, row.cells[column.source]
            ):
                logger.error(
                    "registry provider returned a bad cell: table=%s column=%s",
                    table.id,
                    column.id,
                )
                raise RegistryProviderError(table_id, column.id)

    sort_column = next(c for c in table.columns if c.id == table.default_sort.column)
    rows = _default_sort(rows, sort_column, table.default_sort.direction)

    total = len(rows)
    cap = config.limits.max_rows_per_table
    truncated = total > cap
    rows = rows[:cap]

    return BuiltTable(
        table_id=table.id,
        total=total,
        truncated=truncated,
        generated_at=datetime.now(UTC),
        rows=[
            RegistryRow(
                key=row.key,
                cells={column.id: row.cells[column.source] for column in table.columns},
            )
            for row in rows
        ],
    )


# ── Permanent player numbers (0.11.0 unit 11) ────────────────────────
#
# A Registry number is issued once and never changes or moves to
# another player: ``registry_player_numbers`` maps ``player_id`` to its
# ``number`` and ``registry_number_counter.last_number`` is the only
# source of new ones — it just grows, so a gap left by a deleted
# player stays a gap. ``load_players``/``load_player`` call
# ``ensure_player_numbers`` first; the admin player-info hook reads the
# stored numbers through ``admin_registry_numbers`` and never issues.


async def _player_numbers(
    session: AsyncSession, player_ids: list[str]
) -> dict[str, int]:
    """``{player_id: number}`` of the stored rows for ``player_ids``."""
    if not player_ids:
        return {}
    rows = await session.execute(
        select(RegistryPlayerNumber.player_id, RegistryPlayerNumber.number).where(
            RegistryPlayerNumber.player_id.in_(player_ids)
        )
    )
    return {player_id: number for player_id, number in rows.all()}


async def ensure_player_numbers(session: AsyncSession) -> dict[str, int]:
    """
    Give a permanent Registry number to every player that has none
    (0.11.0 unit 11); returns ``{player_id: number}`` of every current
    player.

    New numbers go out in the (created_at, id) order of
    ``PlayerService.list_for_registry`` (INV-R1 — players are read only
    through 00_core), each ``last_number + 1``. Idempotent: an issued
    number is never rewritten, a counter never rewound. On PostgreSQL
    the module advisory lock serializes the check-then-insert sequence
    between processes and ``uq_registry_player_numbers_number`` is the
    second line of defence; on SQLite the single writer is enough —
    a lost insert race rolls back and retries on the winner's
    committed state (bounded).

    The registry routes never commit the request transaction — they
    were read-only until numbers existed — so the issuing branch
    commits itself; plain reads stay commit-free and the lock is
    released with the commit.
    """
    for attempt in range(3):
        players = await PlayerService.list_for_registry(session)
        player_ids = [row.player_id for row in players]
        numbers = await _player_numbers(session, player_ids)
        missing = [pid for pid in player_ids if pid not in numbers]
        if not missing:
            return numbers

        if session.bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": REGISTRY_NUMBERS_ADVISORY_LOCK_KEY},
            )

        # Re-read under the lock: a concurrent call may have issued
        # some of the missing numbers while this transaction waited
        # for it.
        numbers.update(await _player_numbers(session, missing))
        still_missing = [pid for pid in missing if pid not in numbers]
        if not still_missing:
            return numbers

        counter = (
            await session.execute(
                select(RegistryNumberCounter).where(RegistryNumberCounter.id == 1)
            )
        ).scalar_one_or_none()
        if counter is None:
            # A schema built from Base.metadata alone (tests, a
            # database created before migration 0016 ran) has no
            # counter row: seed it from the highest issued number,
            # never lower.
            highest = (
                await session.execute(select(func.max(RegistryPlayerNumber.number)))
            ).scalar_one() or 0
            counter = RegistryNumberCounter(id=1, last_number=highest)
            session.add(counter)

        next_number = counter.last_number
        for player_id in still_missing:
            next_number += 1
            session.add(RegistryPlayerNumber(player_id=player_id, number=next_number))
            numbers[player_id] = next_number
        counter.last_number = next_number
        try:
            await session.commit()
            return numbers
        except IntegrityError:
            # Lost a race on a dialect without the advisory lock: the
            # winner's commit is now visible — recompute from fresh
            # state instead of surfacing a constraint error.
            await session.rollback()
            if attempt == 2:
                raise

    return numbers  # unreachable — the loop always returns or raises


async def admin_registry_numbers(
    session: AsyncSession, player_ids: list[str]
) -> dict[str, int]:
    """
    Stored Registry numbers for the panel's «Игроки» column
    (0.11.0 unit 11). Read-only like every player-info hook — it never
    issues numbers, so a player the registry has not seen yet simply
    has no key (the panel shows the empty dash).
    """
    return await _player_numbers(session, player_ids)


# ── Admin players table (0.11.0 unit 6b) ─────────────────────────────
#
# The panel's «Игроки» section asks this module for the display names
# it owns — the cached VK profiles. Only status OK rows carry a usable
# name (a PENDING/UNAVAILABLE row can hold stale halves). Both
# functions are read-only and never commit.


async def admin_display_names(
    session: AsyncSession, player_ids: list[str]
) -> dict[str, str]:
    """
    ``first_name last_name`` of each player's cached VK profile —
    OK status only; a player without a usable name has no key.
    """
    if not player_ids:
        return {}
    rows = await session.execute(
        select(
            RegistryVkProfile.player_id,
            RegistryVkProfile.first_name,
            RegistryVkProfile.last_name,
        ).where(
            RegistryVkProfile.player_id.in_(player_ids),
            RegistryVkProfile.status == "OK",
        )
    )
    names: dict[str, str] = {}
    for player_id, first, last in rows.all():
        name = f"{first or ''} {last or ''}".strip()
        if name:
            names[player_id] = name
    return names


async def admin_search_player_ids(session: AsyncSession, text: str) -> set[str]:
    """
    Player ids whose cached OK VK profile's ``first_name last_name``
    contains ``text`` (case-insensitive substring) — the module's
    half of the admin players search. Matched in Python like the
    registry's cell search: SQLite's ``lower()`` only folds ASCII and
    the profiles table is small enough for an admin tool.
    """
    rows = await session.execute(
        select(
            RegistryVkProfile.player_id,
            RegistryVkProfile.first_name,
            RegistryVkProfile.last_name,
        ).where(RegistryVkProfile.status == "OK")
    )
    lowered = text.lower()
    return {
        player_id
        for player_id, first, last in rows.all()
        if lowered in f"{first or ''} {last or ''}".lower()
    }
