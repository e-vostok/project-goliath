"""
HTTP routes of module 03_registry (Spec 5.1, 5.2, 5.6).

Endpoints under ``/api/v1/registry`` behind the shared Bearer JWT
dependency: the table descriptions (``Cache-Control: no-cache`` — the
client revalidates the catalog), the rows of one table and the public
card of one player by his Registry row number
(``Cache-Control: no-store`` — player data is never cached). Every
logged-in player sees the same contents (INV-R10); the responses carry
no ``vk_user_id`` and no player uuid (INV-R2).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security.dependencies import get_current_player
from modules._00_core.models import Player
from modules._03_registry.schemas import (
    RegistryColumnDTO,
    RegistryDefaultSortDTO,
    RegistryLayoutDTO,
    RegistryPlayerDTO,
    RegistryPlayerJoinedDTO,
    RegistryPlayerNationDTO,
    RegistryPlayerPersonDTO,
    RegistryRowDTO,
    RegistryRowsDTO,
    RegistryTableDTO,
    RegistryTablesDTO,
)
from modules._03_registry.service import build_table
from modules._03_registry.sources import load_player
from modules._03_registry.startup import get_registry_config

router = APIRouter(prefix="/api/v1/registry")


@router.get("/tables", response_model=RegistryTablesDTO)
async def list_registry_tables(
    response: Response,
    player: Player = Depends(get_current_player),
) -> RegistryTablesDTO:
    """Spec 5.1 — the description of every configured table."""
    response.headers["Cache-Control"] = "no-cache"
    config = get_registry_config()
    return RegistryTablesDTO(
        layout=RegistryLayoutDTO(tabs_position=config.layout.tabs_position),
        tables=[
            RegistryTableDTO(
                id=table.id,
                title=table.title,
                icon=table.icon,
                empty_text=table.empty_text,
                default_sort=RegistryDefaultSortDTO(
                    column=table.default_sort.column,
                    direction=table.default_sort.direction,
                ),
                columns=[
                    RegistryColumnDTO(
                        id=column.id,
                        title=column.title,
                        type=column.type,
                        width_px=column.width_px,
                        sortable=column.sortable,
                        filters=list(column.filters),
                        filter_label=column.filter_label,
                        header_icon=column.header_icon,
                        searchable=column.searchable,
                        stub=column.stub,
                        scale_min=column.scale_min,
                        scale_max=column.scale_max,
                    )
                    for column in table.columns
                ],
            )
            for table in config.tables
        ],
    )


@router.get("/tables/{table_id}", response_model=RegistryRowsDTO)
async def get_registry_table(
    table_id: str,
    response: Response,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> RegistryRowsDTO:
    """Spec 5.2 — the rows of one table, built on request."""
    response.headers["Cache-Control"] = "no-store"
    built = await build_table(session, table_id)
    return RegistryRowsDTO(
        table_id=built.table_id,
        total=built.total,
        truncated=built.truncated,
        generated_at=built.generated_at.isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        rows=[RegistryRowDTO(key=row.key, cells=row.cells) for row in built.rows],
    )


@router.get("/players/{number}", response_model=RegistryPlayerDTO)
async def get_registry_player(
    number: Annotated[int, Path(ge=1)],
    response: Response,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> RegistryPlayerDTO:
    """
    Spec 5.6 — the public card of one player, addressed by his Registry
    row number (``p<N>`` in the players table). The cells come from the
    same ``_player_row`` the table source builds, so the answer and the
    table row can never disagree; a well-formed ``number`` beyond the
    list is ``404 REGISTRY_PLAYER_NOT_FOUND``.
    """
    response.headers["Cache-Control"] = "no-store"
    row = await load_player(session, number)
    return RegistryPlayerDTO(
        number=number,
        person=RegistryPlayerPersonDTO.model_validate(row.cells["player"]),
        joined=RegistryPlayerJoinedDTO.model_validate(row.cells["joined"]),
        level=int(row.cells["level"]),
        judge_rating=int(row.cells["judge_rating"]),
        nation=(
            RegistryPlayerNationDTO.model_validate(row.cells["nation"])
            if row.cells["nation"] is not None
            else None
        ),
    )
