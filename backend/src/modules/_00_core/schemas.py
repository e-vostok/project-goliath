"""
API DTOs for module 00_core.

Request/response schemas for the endpoints in Spec Part 5. Nation name
length is validated here at the DTO layer against CoreConfig bounds —
on the stripped value (the service layer intentionally does not
re-check it); ``color_hex`` carries the fixed ``#RRGGBB`` pattern. All
content rules of the descriptive fields live in the service layer
(INV-9); DTOs only type them.
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
    """Validate nation name length on the stripped value (config bounds)."""
    if value is None:
        return value
    min_len = CORE_CONFIG.nation.nation_name_min_length
    max_len = CORE_CONFIG.nation.nation_name_max_length
    if not (min_len <= len(value.strip()) <= max_len):
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
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    player: PlayerDTO


class NationDTO(BaseModel):
    """
    Nation representation (Spec Part 5). None on mandatory fields only
    for nations created before the profile/0.8.0 migrations; None on
    optional fields means "not set". ``flag_url``/``portrait_url`` are
    derived through ``catalog.py`` (INV-16).
    """

    id: uuid.UUID
    owner_player_id: uuid.UUID
    created_at: datetime
    name: str
    short_name: str | None
    color_hex: str
    motto: str | None
    description: str | None
    flag_id: str | None
    flag_url: str | None
    province_ids: list[int]
    capital_province_id: int | None
    capital_name: str | None
    leader_name: str | None
    gender: str | None
    leader_title: str | None
    leader_bio: str | None
    portrait_id: str | None
    portrait_url: str | None
    succession_type: str | None
    history_url: str | None
    # не используется с 0.9.0, снятие — бэклог 00_core
    anthem_url: str | None


class NationCreateRequest(BaseModel):
    """Request body for POST /api/v1/nations."""

    name: str
    short_name: str
    color_hex: str = Field(pattern=_COLOR_HEX_PATTERN)
    motto: str | None = None
    description: str | None = None
    flag_id: str | None = None
    province_ids: list[int]
    capital_province_id: int | None = None
    capital_name: str
    leader_name: str
    gender: str
    leader_title: str
    leader_bio: str | None = None
    portrait_id: str | None = None
    succession_type: str
    history_url: str
    anthem_url: str | None = None

    @field_validator("name")
    @classmethod
    def check_name_length(cls, value: str) -> str:
        return _validate_nation_name(value)


class NationUpdateRequest(BaseModel):
    """
    Request body for PATCH /api/v1/nations/me.

    None/absent means "do not change"; "" on an optional field clears
    it to NULL; "" on a mandatory field is a service-layer error
    (INV-8). ``province_ids``/``capital_province_id`` are not declared
    (INV-14): stray keys are ignored, as before.
    """

    name: str | None = None
    short_name: str | None = None
    color_hex: str | None = Field(default=None, pattern=_COLOR_HEX_PATTERN)
    motto: str | None = None
    description: str | None = None
    flag_id: str | None = None
    capital_name: str | None = None
    leader_name: str | None = None
    gender: str | None = None
    leader_title: str | None = None
    leader_bio: str | None = None
    portrait_id: str | None = None
    succession_type: str | None = None
    history_url: str | None = None
    anthem_url: str | None = None

    @field_validator("name")
    @classmethod
    def check_name_length(cls, value: str | None) -> str | None:
        return _validate_nation_name(value)


class CatalogItemDTO(BaseModel):
    """One ready-made catalog asset (flag or portrait)."""

    id: str
    url: str


class NationRulesDTO(BaseModel):
    """
    Nation creation/update limits plus the selectable value sets,
    served from CoreConfig and code constants for UI hints (Spec
    Part 5). Color thresholds are intentionally not exposed.
    """

    name_min_length: int
    name_max_length: int
    short_name_min_length: int
    short_name_max_length: int
    motto_max_length: int
    description_max_length: int
    leader_name_min_length: int
    leader_name_max_length: int
    leader_title_min_length: int
    leader_title_max_length: int
    leader_bio_max_length: int
    capital_name_min_length: int
    capital_name_max_length: int
    history_url_max_length: int
    history_url_allowed_hosts: list[str]
    anthem_url_max_length: int
    anthem_url_allowed_hosts: list[str]
    min_provinces: int
    max_provinces: int
    palette: list[str]
    flags: list[CatalogItemDTO]
    portraits: list[CatalogItemDTO]
    genders: list[str]
    succession_types: list[str]


class ColorCheckRequest(BaseModel):
    """Request body for POST /api/v1/nations/color-check."""

    color_hex: str = Field(pattern=_COLOR_HEX_PATTERN)


class ColorCheckDTO(BaseModel):
    """The Part 3 color decision for the input hint."""

    status: Literal["OK", "TAKEN", "TOO_CLOSE"]


class ProvinceDTO(BaseModel):
    """Province representation (Spec 01_map Part 5 adds ``kind``)."""

    id: int
    nation_id: uuid.UUID | None
    kind: Literal["LAND", "SEA"]


class GameClockDTO(BaseModel):
    """Game clock representation."""

    current_turn: int
    game_date: str
    game_date_text: str
    next_tick_at: datetime


class ErrorResponse(BaseModel):
    """Standard error body."""

    detail: str
    code: str
