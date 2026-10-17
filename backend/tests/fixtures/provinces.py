"""
Province (map node) factories for tests.

Migration 0006 removed the placeholder rows ``id 1..100``; real map node
ids start at 1001. These helpers seed provinces with safe defaults —
LAND ids from 1001, SEA ids from 2001 — so no test ever touches the old
placeholder range or confuses a sea zone for ownable land.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.models import Province

# The mini map that lifespan-booting tests point MAP_DATA_DIR at — the
# startup sync inserts exactly these nodes (Spec Part 2), so a factory
# row and the synced row for the same id always agree on kind.
MAP_MINI_DIR = Path(__file__).resolve().parent / "map_mini"

# A variant of the mini map with an extra strait edge 1004-1005: the
# land nodes 1001..1007 form one connected group, so a valid
# Registration-2.0 starting set of exactly 5 exists (the canonical
# mini map stays split into components of 4/3/1 on purpose — the
# connectivity tests rely on that topology).
MAP_MINI_LINKED_DIR = Path(__file__).resolve().parent / "map_mini_linked"

# The canonical valid starting set: 5 LAND ids, connected on the
# linked mini-map (1001..1004 land chain + the 1004-1005 strait).
STARTING_GROUP: tuple[int, ...] = (1001, 1002, 1003, 1004, 1005)


def map_mini_node_ids() -> tuple[int, ...]:
    """All node ids of the mini-map fixture, ascending."""
    manifest = json.loads((MAP_MINI_DIR / "manifest.json").read_text(encoding="utf-8"))
    return tuple(sorted(node["id"] for node in manifest["nodes"]))


def map_mini_linked_node_ids() -> tuple[int, ...]:
    """All node ids of the linked mini-map fixture, ascending."""
    manifest = json.loads(
        (MAP_MINI_LINKED_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    return tuple(sorted(node["id"] for node in manifest["nodes"]))


_land_ids = itertools.count(1001)
_sea_ids = itertools.count(2001)


async def _make_province(session: AsyncSession, kind: str, id: int | None) -> Province:
    """
    Return the province with `id`, inserting it when absent. The startup
    sync may already have created the row from the mini-map fixture —
    reuse it instead of raising a duplicate-PK error; the factory kind
    and the synced kind agree by construction.
    """
    province_id = (
        id if id is not None else next(_land_ids if kind == "LAND" else _sea_ids)
    )
    existing = await session.get(Province, province_id)
    if existing is not None:
        return existing
    province = Province(id=province_id, kind=kind, nation_id=None)
    session.add(province)
    await session.flush()
    return province


async def make_land_province(session: AsyncSession, id: int | None = None) -> Province:
    """Insert one LAND province (id defaults to the next from 1001)."""
    return await _make_province(session, "LAND", id)


async def make_sea_province(session: AsyncSession, id: int | None = None) -> Province:
    """Insert one SEA zone (id defaults to the next from 2001)."""
    return await _make_province(session, "SEA", id)


async def make_starting_group(
    session: AsyncSession,
) -> list[int]:
    """
    Seed the canonical 5-province starting set (STARTING_GROUP) and
    return its ids — exactly ``max_provinces_per_nation`` land rows for
    Registration-2.0 tests.
    """
    for pid in STARTING_GROUP:
        await make_land_province(session, id=pid)
    return list(STARTING_GROUP)


@dataclass(frozen=True)
class ProvinceSet:
    """A ready-made small map: 5 land nodes and 2 sea zones."""

    land_ids: list[int]
    sea_ids: list[int]


async def make_province_set(session: AsyncSession) -> ProvinceSet:
    """Seed the default mini-map: land 1001..1005, sea 2001..2002."""
    land_ids = [1001, 1002, 1003, 1004, 1005]
    sea_ids = [2001, 2002]
    for pid in land_ids:
        await make_land_province(session, id=pid)
    for pid in sea_ids:
        await make_sea_province(session, id=pid)
    return ProvinceSet(land_ids=land_ids, sea_ids=sea_ids)
