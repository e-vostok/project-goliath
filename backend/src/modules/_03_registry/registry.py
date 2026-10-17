"""
Table-source registry of module 03_registry — the public API for
data-owning modules (Spec 2.6, Appendix A).

A table source is ``(key, provides, load)``: ``provides`` declares the
value keys the source's rows can carry, ``load`` is an async callable
that reads its own module's public functions and returns ``RegistryRow``
objects. One table — one source; a config column references one key of
``provides`` via ``columns[].source``. Registering an existing key
replaces the previous source (like ``register_nation_created_hook``),
which keeps ``startup_registry()`` idempotent across repeated app boots.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

# A cell's JSON shape per column type — Spec 3.6.
Cell = int | str | dict | None


@dataclass(frozen=True)
class RegistryRow:
    """
    One row of a built table: a response-stable ``key`` (a player number
    ``p<N>`` or a nation id — never a ``vk_user_id`` or a player uuid,
    INV-R2) and the value-key -> cell mapping.
    """

    key: str
    cells: dict[str, Cell]


LoadFn = Callable[[AsyncSession], Awaitable[list[RegistryRow]]]


@dataclass(frozen=True)
class TableSource:
    """A registered table source (Appendix A)."""

    key: str
    provides: frozenset[str]
    load: LoadFn


_sources: dict[str, TableSource] = {}


def register_table_source(
    key: str,
    provides: frozenset[str],
    load: LoadFn,
) -> None:
    """
    Register a table source (Appendix A). A repeated key replaces the
    previous registration — startup stays idempotent and tests can swap
    a builtin source for a failing double.
    """
    _sources[key] = TableSource(
        key=key, provides=frozenset(provides), load=load
    )


def get_table_source(key: str) -> TableSource | None:
    """The registered source for ``key``, or None."""
    return _sources.get(key)


def get_table_sources() -> dict[str, TableSource]:
    """All registered sources, keyed by source key (a copy)."""
    return dict(_sources)


def clear_registry() -> None:
    """Drop every registration — test isolation."""
    _sources.clear()
