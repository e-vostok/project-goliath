"""
Read-only pre-deploy report on retired map nodes (map_polish_2b).

Run from ``backend/`` (after ``pip install -e ".[dev]"``)::

    python -m modules._01_map.retired_report

or, on the deploy track, inside the backend image::

    docker compose run --rm backend python -m modules._01_map.retired_report

It answers "would ``startup_map()`` succeed on THIS database?" before
the new version is started, and it changes nothing: the same map
validation runs first (a :class:`MapDataError` prints and exits 2), the
database is resolved by ``core.settings.resolve_database_url`` — the
same rule the app and Alembic use, environment first then the repo-root
``.env``, no silent fallback — the map directory is ``startup.py``'s
own ``resolve_data_dir`` (``MAP_DATA_DIR`` else ``<repo>/data/map``),
and every query is a SELECT inside a session that is rolled back,
never committed.

Exit codes: 0 — ГОТОВО, the startup sync would pass; 1 — СТОП, it
would abort (owned or journal-carrying retired rows, unknown extra
rows, kind mismatches — all listed); 2 — the map data itself failed
validation.

Internal to module ``_01_map``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

# Same convention as alembic/env.py: make backend/src importable no
# matter how the module was reached — `python -m src.modules._01_map.
# retired_report` from backend/ (and inside the Docker image, which
# never installs the project), or `python -m modules._01_map.
# retired_report` from backend/src.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.settings import format_database_target, resolve_database_url
from modules._00_core.models import Nation, Province
from modules._01_map.config_schema import MapConfig
from modules._01_map.loader import MapDataError, load_map_data
from modules._01_map.map_data import KIND_LAND, MapData
from modules._01_map.models import MapOwnershipLog
from modules._01_map.startup import resolve_data_dir

EXIT_OK = 0
EXIT_STOP = 1
EXIT_MAP_DATA = 2

_IDS_LOCK = "ids.lock.json"
_MAX_LISTED = 20


@dataclass(frozen=True)
class OwnedRetired:
    """A retired province row still owned by a nation — fatal at startup."""

    province_id: int
    nation_id: str
    nation_name: str | None


@dataclass(frozen=True)
class JournalStat:
    """map_ownership_log volume behind one retired province row."""

    province_id: int
    row_count: int
    turn_min: int
    turn_max: int


@dataclass(frozen=True)
class RetiredReport:
    """
    Everything the report knows about one database (all lists sorted).

    ``ok`` mirrors the startup verdict: owned or journal-carrying
    retired rows, extra rows unknown to ids.lock.json, and kind
    mismatches each abort ``startup_map()`` — RETIRED_PROVINCE_OWNED,
    RETIRED_PROVINCE_HISTORY and INV_M5 respectively.
    """

    target: str
    data_dir: Path
    geometry_version: str
    manifest_total: int
    manifest_land: int
    manifest_sea: int
    retired_ids: tuple[int, ...]
    provinces_total: int
    missing_manifest: tuple[int, ...]
    present_retired: tuple[int, ...]
    present_land: int
    present_sea: int
    owned: tuple[OwnedRetired, ...]
    journal: tuple[JournalStat, ...]
    unknown_extra: tuple[int, ...]
    kind_mismatch: tuple[tuple[int, str, str], ...]
    key_by_id: Mapping[int, str]

    @property
    def ok(self) -> bool:
        """True when nothing would abort the startup sync."""
        return not (
            self.owned
            or self.journal
            or self.unknown_extra
            or self.kind_mismatch
        )

    @property
    def removable(self) -> int:
        """Retired rows startup would delete; 0 whenever it stops first."""
        return len(self.present_retired) if self.ok else 0


async def collect_report(
    session: AsyncSession,
    map_data: MapData,
    *,
    target: str,
    data_dir: Path,
    key_by_id: Mapping[int, str],
) -> RetiredReport:
    """
    SELECT-only probe mirroring ``startup_map()``'s INV-M5/1.9 logic.

    Reads ``provinces``, ``nations`` and ``map_ownership_log``; never
    writes, never commits — the caller rolls the session back.
    """
    retired = set(map_data.retired_ids)
    rows = (
        await session.execute(select(Province.id, Province.kind))
    ).all()
    db_kinds = {row[0]: row[1] for row in rows}

    present = sorted(retired & set(db_kinds))
    owned: list[OwnedRetired] = []
    journal: list[JournalStat] = []
    if present:
        rows = (
            await session.execute(
                select(Province.id, Province.nation_id, Nation.name)
                .outerjoin(Nation, Province.nation_id == Nation.id)
                .where(Province.id.in_(present))
                .order_by(Province.id)
            )
        ).all()
        owned = [
            OwnedRetired(row[0], row[1], row[2])
            for row in rows
            if row[1] is not None
        ]
        stats = (
            await session.execute(
                select(
                    MapOwnershipLog.province_id,
                    func.count(),
                    func.min(MapOwnershipLog.turn_number),
                    func.max(MapOwnershipLog.turn_number),
                )
                .where(MapOwnershipLog.province_id.in_(present))
                .group_by(MapOwnershipLog.province_id)
                .order_by(MapOwnershipLog.province_id)
            )
        ).all()
        journal = [
            JournalStat(row[0], row[1], row[2], row[3]) for row in stats
        ]

    nodes = map_data.nodes
    missing = sorted(set(nodes) - set(db_kinds))
    unknown = sorted(set(db_kinds) - set(nodes) - retired)
    mismatch = tuple(
        sorted(
            (node_id, db_kinds[node_id], nodes[node_id].kind)
            for node_id in set(db_kinds) & set(nodes)
            if db_kinds[node_id] != nodes[node_id].kind
        )
    )
    land = sum(1 for n in nodes.values() if n.kind == KIND_LAND)
    present_land = sum(1 for i in present if db_kinds[i] == KIND_LAND)
    return RetiredReport(
        target=target,
        data_dir=data_dir,
        geometry_version=map_data.geometry_version,
        manifest_total=len(nodes),
        manifest_land=land,
        manifest_sea=len(nodes) - land,
        retired_ids=map_data.retired_ids,
        provinces_total=len(db_kinds),
        missing_manifest=tuple(missing),
        present_retired=tuple(present),
        present_land=present_land,
        present_sea=len(present) - present_land,
        owned=tuple(owned),
        journal=tuple(journal),
        unknown_extra=tuple(unknown),
        kind_mismatch=mismatch,
        key_by_id=key_by_id,
    )


def _rows_word(n: int) -> str:
    """Russian plural of 'строка' for the verdict line."""
    if 10 < n % 100 < 20:
        return "строк"
    return {1: "строка", 2: "строки", 3: "строки", 4: "строки"}.get(
        n % 10, "строк"
    )


def format_report(report: RetiredReport) -> list[str]:
    """Human-readable Russian text — one list entry per output line."""
    r = report

    def key(province_id: int) -> str:
        return r.key_by_id.get(province_id, "?")

    lines = [
        f"Карта: {r.data_dir}",
        f"Версия геометрии: {r.geometry_version}",
        f"Узлов в manifest.json: {r.manifest_total} "
        f"(LAND: {r.manifest_land}, SEA: {r.manifest_sea})",
        f"Выведенных id в ids.lock.json (нет в manifest.json): "
        f"{len(r.retired_ids)}",
        f"Строк в таблице provinces: {r.provinces_total}",
        f"Узлов манифеста ещё нет в базе: {len(r.missing_manifest)} "
        "(будут созданы при запуске)",
        "",
    ]
    absent = len(r.retired_ids) - len(r.present_retired)
    lines.append(
        f"Выведенные узлы со строками в provinces: "
        f"{len(r.present_retired)} "
        f"(LAND: {r.present_land}, SEA: {r.present_sea}); "
        f"уже отсутствуют: {absent}"
    )
    if r.owned:
        lines.append(
            "  ПРИНАДЛЕЖАТ НАЦИЯМ — запуск остановится "
            "(RETIRED_PROVINCE_OWNED):"
        )
        for o in r.owned:
            lines.append(
                f"    id {o.province_id} ({key(o.province_id)}) — "
                f"нация {o.nation_id} «{o.nation_name}»"
            )
    if r.journal:
        lines.append(
            "  ЕСТЬ ЗАПИСИ В ЖУРНАЛЕ map_ownership_log — запуск "
            "остановится (RETIRED_PROVINCE_HISTORY):"
        )
        for j in r.journal:
            lines.append(
                f"    id {j.province_id} ({key(j.province_id)}) — "
                f"записей: {j.row_count}, ходы "
                f"{j.turn_min}–{j.turn_max}"
            )
    if r.unknown_extra:
        shown = ", ".join(
            str(i) for i in r.unknown_extra[:_MAX_LISTED]
        )
        if len(r.unknown_extra) > _MAX_LISTED:
            shown += f" и ещё {len(r.unknown_extra) - _MAX_LISTED}"
        lines.append(
            "Посторонние строки в provinces — их id нет ни в "
            "manifest.json, ни в ids.lock.json (INV_M5):"
        )
        lines.append(f"  {shown}")
    if r.kind_mismatch:
        lines.append(
            "Тип узла в базе не совпадает с manifest.json (INV_M5):"
        )
        for node_id, db_kind, manifest_kind in r.kind_mismatch[
            :_MAX_LISTED
        ]:
            lines.append(
                f"  id {node_id}: в базе {db_kind}, "
                f"в manifest.json {manifest_kind}"
            )
        if len(r.kind_mismatch) > _MAX_LISTED:
            lines.append(
                f"  ... и ещё {len(r.kind_mismatch) - _MAX_LISTED}"
            )

    lines.append("")
    if r.ok:
        lines.append(
            f"ГОТОВО: запуск пройдёт, будет удалено {r.removable} "
            f"{_rows_word(r.removable)}"
        )
    else:
        lines.append("СТОП: запуск остановится")
        lines.append("Причины:")
        if r.owned:
            lines.append(
                f"  - выведенных провинций, принадлежащих нациям: "
                f"{len(r.owned)} (RETIRED_PROVINCE_OWNED)"
            )
        if r.journal:
            lines.append(
                f"  - выведенных провинций с записями в журнале: "
                f"{len(r.journal)} (RETIRED_PROVINCE_HISTORY)"
            )
        if r.unknown_extra:
            lines.append(
                f"  - посторонних строк в provinces: "
                f"{len(r.unknown_extra)} (INV_M5)"
            )
        if r.kind_mismatch:
            lines.append(
                f"  - несовпадений типа узла с manifest.json: "
                f"{len(r.kind_mismatch)} (INV_M5)"
            )
    return lines


async def run() -> int:
    """
    The report coroutine: resolve, validate, probe, print, verdict.

    Returns the process exit code; ``main()`` wraps it in asyncio.run.
    """
    url = resolve_database_url()
    target = format_database_target(url)
    print(f"Target: {target}")

    config = MapConfig.from_yaml(MapConfig.get_default_config_path())
    data_dir = resolve_data_dir()
    try:
        map_data = load_map_data(data_dir, config)
    except MapDataError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return EXIT_MAP_DATA

    # MapData carries retired ids but not their keys — re-read the lock
    # (already validated by load_map_data) for the display names.
    lock_doc = json.loads(
        (data_dir / _IDS_LOCK).read_text(encoding="utf-8")
    )
    key_by_id = {i: k for k, i in lock_doc["ids"].items()}

    engine = create_async_engine(url)
    try:
        maker = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with maker() as session:
            report = await collect_report(
                session,
                map_data,
                target=target,
                data_dir=data_dir,
                key_by_id=key_by_id,
            )
            # Read-only guarantee: the session is never committed.
            await session.rollback()
    finally:
        await engine.dispose()

    for line in format_report(report):
        print(line)
    return EXIT_OK if report.ok else EXIT_STOP


def main() -> int:
    """Synchronous entry point for ``python -m``."""
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
