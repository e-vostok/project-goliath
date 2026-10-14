"""
Response schemas of module 03_registry (Spec 5.1, 5.2).

The ``source`` fields of the config (table source key, column value
keys) are deliberately absent — the client addresses cells by column id
and never learns which module supplies the data.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class RegistryLayoutDTO(BaseModel):
    """``RegistryTablesDTO.layout`` — window layout rules."""

    tabs_position: Literal["top", "right"]


class RegistryColumnDTO(BaseModel):
    """One column of ``RegistryTableDTO`` — the Spec 5.1 shape."""

    id: str
    title: str
    type: str
    width_px: int
    sortable: bool
    filters: list[str]
    filter_label: str | None
    searchable: bool
    stub: bool
    scale_min: int | None
    scale_max: int | None


class RegistryDefaultSortDTO(BaseModel):
    """``RegistryTableDTO.default_sort``."""

    column: str
    direction: Literal["asc", "desc"]


class RegistryTableDTO(BaseModel):
    """One table description in ``RegistryTablesDTO.tables``."""

    id: str
    title: str
    icon: str
    empty_text: str
    default_sort: RegistryDefaultSortDTO
    columns: list[RegistryColumnDTO]


class RegistryTablesDTO(BaseModel):
    """Response for ``GET /api/v1/registry/tables`` (Spec 5.1)."""

    layout: RegistryLayoutDTO
    tables: list[RegistryTableDTO]


class RegistryRowDTO(BaseModel):
    """One row of ``RegistryRowsDTO`` — cells keyed by column id."""

    key: str
    cells: dict[str, Any]


class RegistryRowsDTO(BaseModel):
    """Response for ``GET /api/v1/registry/tables/{table_id}`` (Spec 5.2)."""

    table_id: str
    total: int
    truncated: bool
    # "YYYY-MM-DDTHH:MM:SSZ" — the client never parses dates itself.
    generated_at: str
    rows: list[RegistryRowDTO]
