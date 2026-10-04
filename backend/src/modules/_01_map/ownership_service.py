"""
Ownership journal service — the ONLY reader/writer of map_ownership_log.

Data sovereignty (Spec Part 2): this table belongs to 01_map. Rows are
appended by :func:`record_changes`, which runs inside the caller's
transaction via the core ownership-listener registry (INV-M7) — the
service never commits by itself. Rows are wiped only by
:func:`clear_all`, used exclusively by the registered world-reset hook.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.hooks import OwnershipChange
from modules._01_map.models import MapOwnershipLog


@dataclass(frozen=True)
class OwnerAtTurn:
    """
    Owner of a province at turn T (formula 3.5).

    ``name``/``color`` are the values stored on the ownership EVENT —
    later renames of the nation do not rewrite history.
    """

    nation_id: str
    name: str
    color: str


def _validate_consistency(change: OwnershipChange) -> None:
    """Mirror ck_log_new_nation_consistent before hitting the database."""
    is_release = change.new_nation_id is None
    if (change.new_name is None) != is_release or (
        change.new_color is None
    ) != is_release:
        raise ValueError(
            "OwnershipChange new_nation_id/new_name/new_color must be "
            "all set (claim) or all None (release): "
            f"province {change.province_id}"
        )


async def record_changes(
    session: AsyncSession, changes: Sequence[OwnershipChange]
) -> None:
    """
    Append one journal row per ownership change, in the caller's
    transaction. Flushes but never commits — INV-M7 keeps the row and
    the ownership mutation in one atomic unit.
    """
    now = datetime.now(timezone.utc)
    for change in changes:
        _validate_consistency(change)
        session.add(
            MapOwnershipLog(
                province_id=change.province_id,
                turn_number=change.turn,
                prev_nation_id=change.prev_nation_id,
                new_nation_id=change.new_nation_id,
                new_nation_name=change.new_name,
                new_nation_color=change.new_color,
                created_at=now,
            )
        )
    if changes:
        await session.flush()


async def clear_all(session: AsyncSession) -> None:
    """
    Wipe the whole journal — called ONLY by the registered world-reset
    hook (INV-M8). There is intentionally no other UPDATE/DELETE path.
    """
    await session.execute(delete(MapOwnershipLog))


async def province_ids_with_journal(
    session: AsyncSession, province_ids: Iterable[int]
) -> set[int]:
    """
    Which of ``province_ids`` have at least one journal row.

    Read-only probe used by startup synchronisation (INV-M5, 1.9): a
    retired province row carrying journal history must not be deleted —
    the FK forbids it on PostgreSQL and would orphan append-only history.
    """
    ids = list(province_ids)
    if not ids:
        return set()
    result = await session.execute(
        select(MapOwnershipLog.province_id)
        .where(MapOwnershipLog.province_id.in_(ids))
        .distinct()
    )
    return {row[0] for row in result.all()}


async def owners_at_turn(
    session: AsyncSession, turn: int
) -> dict[int, OwnerAtTurn]:
    """
    Snapshot of ownership at ``turn`` (formula 3.5).

    For each province takes the record with the greatest
    (turn_number, id) among rows with turn_number <= turn; provinces
    whose latest record is a release — or that have no record — are
    absent from the result. One query using a window function portable
    across SQLite >= 3.25 and PostgreSQL.
    """
    if turn < 0:
        raise ValueError(f"turn must be >= 0, got {turn}")

    rn = (
        func.row_number()
        .over(
            partition_by=MapOwnershipLog.province_id,
            order_by=(
                MapOwnershipLog.turn_number.desc(),
                MapOwnershipLog.id.desc(),
            ),
        )
        .label("rn")
    )
    latest = (
        select(
            MapOwnershipLog.province_id,
            MapOwnershipLog.new_nation_id,
            MapOwnershipLog.new_nation_name,
            MapOwnershipLog.new_nation_color,
            rn,
        )
        .where(MapOwnershipLog.turn_number <= turn)
        .subquery()
    )
    result = await session.execute(
        select(
            latest.c.province_id,
            latest.c.new_nation_id,
            latest.c.new_nation_name,
            latest.c.new_nation_color,
        )
        .where(latest.c.rn == 1)
        .where(latest.c.new_nation_id.is_not(None))
    )
    return {
        row.province_id: OwnerAtTurn(
            nation_id=row.new_nation_id,
            name=row.new_nation_name,
            color=row.new_nation_color,
        )
        for row in result.all()
    }


async def records_for_province(
    session: AsyncSession, province_id: int
) -> list[MapOwnershipLog]:
    """Full journal of one province, ordered by (turn_number, id)."""
    result = await session.execute(
        select(MapOwnershipLog)
        .where(MapOwnershipLog.province_id == province_id)
        .order_by(MapOwnershipLog.turn_number, MapOwnershipLog.id)
    )
    return list(result.scalars().all())
