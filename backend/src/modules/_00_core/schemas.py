"""
API DTOs for module 00_core.

Request/response schemas for the endpoints in Spec Part 5. Nation name
length is validated here at the DTO layer against CoreConfig bounds
(the service layer intentionally does not re-check it).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from modules._00_core.config_schema import CoreConfig

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

_COLOR_HEX_PATTERN = r"^#[0-9A-Fa-f]{6}$"


def _validate_nation_name(value: str | None) -> str | None:
    """Validate nation name length against CoreConfig.nation bounds."""
    if value is None:
        return value
    min_len = CORE_CONFIG.nation.nation_name_min_length
    max_len = CORE_CONFIG.nation.nation_name_max_length
    if not (min_len <= len(value) <= max_len):
        raise ValueError(
            f"Nation name length must be between {min_len} and {max_len} characters"
        )
    return value


class VkAuthRequest(BaseModel):
    """Request body for POST /api/v1/auth/vk."""

    launch_params: str


class PlayerDTO(BaseModel):
    """Player representation."""

    id: uuid.UUID
    vk_user_id: int
    created_at: datetime


class AuthResponseDTO(BaseModel):
    """Response for POST /api/v1/auth/vk."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    player: PlayerDTO


class NationDTO(BaseModel):
    """Nation representation."""

    id: uuid.UUID
    name: str
    color_hex: str
    owner_player_id: uuid.UUID
    province_ids: list[int]
    created_at: datetime


class NationCreateRequest(BaseModel):
    """Request body for POST /api/v1/nations."""

    name: str
    color_hex: str = Field(pattern=_COLOR_HEX_PATTERN)
    province_ids: list[int]

    @field_validator("name")
    @classmethod
    def check_name_length(cls, value: str) -> str:
        return _validate_nation_name(value)


class NationUpdateRequest(BaseModel):
    """Request body for PATCH /api/v1/nations/me."""

    name: str | None = None
    color_hex: str | None = Field(default=None, pattern=_COLOR_HEX_PATTERN)

    @field_validator("name")
    @classmethod
    def check_name_length(cls, value: str | None) -> str | None:
        return _validate_nation_name(value)


class NationDeleteRequest(BaseModel):
    """Request body for DELETE /api/v1/nations/me."""

    confirm: Literal[True]


class ProvinceDTO(BaseModel):
    """Province representation."""

    id: int
    nation_id: uuid.UUID | None


class GameClockDTO(BaseModel):
    """Game clock representation."""

    current_turn: int
    game_date: str
    next_tick_at: datetime


class ErrorResponse(BaseModel):
    """Standard error body."""

    detail: str
    code: str
