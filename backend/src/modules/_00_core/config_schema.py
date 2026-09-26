"""
Pydantic-схема валидации баланса модуля 00_core.

Загружает и валидирует configs/00_core.yaml при старте приложения и в CI
(pytest tests/test_configs_validity.py). Некорректный баланс обязан
прерывать запуск сервера до открытия первого соединения.
"""

from __future__ import annotations

from datetime import date
from typing import Self

import yaml
from pydantic import BaseModel, Field, model_validator


class TickSettings(BaseModel):
    tick_interval_hours: int = Field(
        ge=1,
        le=168,
        description="Интервал реального времени между тиками, часы.",
    )


class AuthSettings(BaseModel):
    vk_ts_freshness_window_minutes: int = Field(
        ge=1,
        le=120,
        description="Допустимое окно свежести vk_ts launch-параметров, минуты.",
    )
    jwt_ttl_minutes: int = Field(
        ge=5,
        le=1440,
        description="Время жизни сессионного Bearer JWT, минуты.",
    )


class NationSettings(BaseModel):
    nation_name_min_length: int = Field(ge=1, le=10)
    nation_name_max_length: int = Field(ge=1, le=100)
    min_provinces_per_nation: int = Field(
        ge=0,
        le=10,
        description="Минимум провинций, требуемый для существования государства.",
    )
    max_provinces_per_nation: int = Field(
        ge=1,
        le=200,
        description="Максимум провинций на одно государство.",
    )

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        if self.nation_name_min_length > self.nation_name_max_length:
            raise ValueError(
                "nation_name_min_length не может превышать nation_name_max_length"
            )
        if self.min_provinces_per_nation > self.max_provinces_per_nation:
            raise ValueError(
                "min_provinces_per_nation не может превышать max_provinces_per_nation"
            )
        return self


class CalendarSettings(BaseModel):
    epoch_start_date: date
    days_per_turn: int = Field(
        ge=1,
        le=365,
        description="Количество игровых суток, проходящих за один ход.",
    )


class CoreConfig(BaseModel):
    """Корневая модель конфигурации модуля 00_core."""

    tick: TickSettings
    auth: AuthSettings
    nation: NationSettings
    calendar: CalendarSettings

    @classmethod
    def from_yaml(cls, path: str) -> "CoreConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)
    
    @classmethod
    def get_default_config_path(cls) -> str:
        """
        Get the default path to the 00_core.yaml config file.
        
        This method resolves the path relative to the module location,
        working correctly whether called from backend/src or backend/tests.
        """
        import os
        # This file is at: backend/src/modules/_00_core/config_schema.py
        # Config is at: configs/00_core.yaml
        # We need to go: _00_core -> modules -> src -> backend -> project_root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        project_root = os.path.dirname(backend_dir)
        return os.path.join(project_root, "configs", "00_core.yaml")


if __name__ == "__main__":
    # Ручная проверка: python -m backend.src.modules.00_core.config_schema
    config = CoreConfig.from_yaml("configs/00_core.yaml")
    print(config.model_dump_json(indent=2))