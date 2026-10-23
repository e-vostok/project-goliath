"""
Response schemas of module 03_registry (Spec 5.1, 5.2, 5.6).

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
    header_icon: str | None
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


class RegistryPlayerPersonDTO(BaseModel):
    """``person`` of ``RegistryPlayerDTO`` — the Spec 3.6 ``person`` cell
    (the ``player`` cell of the players table)."""

    name: str
    avatar_url: str | None
    is_fallback: bool


class RegistryPlayerJoinedDTO(BaseModel):
    """``joined`` of ``RegistryPlayerDTO`` — the Spec 3.6 ``date`` cell."""

    text: str
    key: int


class RegistryPlayerNationDTO(BaseModel):
    """``nation`` of ``RegistryPlayerDTO`` — the Spec 3.6 ``nation``
    cell; ``name`` is the nation's short name."""

    id: str | None
    name: str
    color: str
    flag_url: str | None


class RegistryPlayerDTO(BaseModel):
    """
    Response for ``GET /api/v1/registry/players/{number}`` (Spec 5.6) —
    exactly the cells the players table shows in row ``p<N>`` and
    nothing more (INV-R2: no ``player_id``, no ``vk_user_id``).
    """

    number: int
    person: RegistryPlayerPersonDTO
    joined: RegistryPlayerJoinedDTO
    level: int
    judge_rating: int
    nation: RegistryPlayerNationDTO | None
