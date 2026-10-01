"""
Pydantic-схема валидации баланса модуля 01_map.
 
Загружает и валидирует configs/01_map.yaml при старте приложения и в CI
(pytest tests/test_configs_validity.py). Некорректный баланс обязан
прерывать запуск сервера до открытия первого соединения.
 
В отличие от 00_core, схема запрещает неизвестные ключи (extra="forbid"):
опечатка в имени ключа ломает запуск, а не молча игнорируется.
"""
 
from __future__ import annotations
 
import os
import re
from typing import Literal, Self
 
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
 
# Цвет вида #RRGGBB (регистр не важен).
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
 
 
class _Strict(BaseModel):
    """Базовый класс секций: неизвестные ключи запрещены."""
 
    model_config = ConfigDict(extra="forbid")
 
 
class ViewSettings(_Strict):
    zoom_min: float = Field(
        ge=0.5,
        le=1.0,
        description="Минимальный масштаб; 1.0 = карта целиком вписана в окно.",
    )
    zoom_max: float = Field(
        ge=2.0,
        le=40.0,
        description="Максимальный масштаб относительно вписанного вида.",
    )
    pan_margin_fraction: float = Field(
        ge=0.0,
        le=0.5,
        description="Допустимый отступ за край поля при перетаскивании, доля размера окна.",
    )
    label_min_width_px: int = Field(
        ge=20,
        le=400,
        description="Подпись узла показывается, если его ширина на экране не меньше, px.",
    )
    search_min_chars: int = Field(
        ge=1,
        le=5,
        description="Минимум символов для запуска поиска по названию.",
    )
    search_max_results: int = Field(
        ge=5,
        le=100,
        description="Максимум результатов в списке поиска.",
    )
 
    @model_validator(mode="after")
    def check_zoom_order(self) -> Self:
        if self.zoom_min >= self.zoom_max:
            raise ValueError("view.zoom_min must be less than view.zoom_max")
        return self
 
 
class RefreshSettings(_Strict):
    tick_refresh_delay_seconds: int = Field(
        ge=0,
        le=300,
        description="Пауза после времени смены хода перед запросом состояния, сек.",
    )
    tick_refresh_jitter_seconds: int = Field(
        ge=0,
        le=300,
        description="Случайный разброс запроса состояния, сек.",
    )
    retry_delay_seconds: int = Field(
        ge=1,
        le=300,
        description="Пауза перед повтором неудавшегося запроса, сек.",
    )
    max_retries: int = Field(
        ge=0,
        le=10,
        description="Число повторов подряд до пометки «данные устарели».",
    )
    stale_after_seconds: int = Field(
        ge=60,
        le=86400,
        description="Возраст данных, после которого при ошибках они помечаются устаревшими, сек.",
    )
 
 
class ColorSettings(_Strict):
    neutral_province: str = Field(pattern=_HEX_COLOR_RE.pattern)
    sea: str = Field(pattern=_HEX_COLOR_RE.pattern)
    outside: str = Field(pattern=_HEX_COLOR_RE.pattern)
    province_border: str = Field(pattern=_HEX_COLOR_RE.pattern)
    hover: str = Field(pattern=_HEX_COLOR_RE.pattern)
    selected: str = Field(pattern=_HEX_COLOR_RE.pattern)
 
    @model_validator(mode="after")
    def check_base_colors_distinct(self) -> Self:
        # Базовые заливки карты должны различаться, иначе суша, море и
        # земли за краем сольются.
        base = [
            self.neutral_province.upper(),
            self.sea.upper(),
            self.outside.upper(),
        ]
        if len(set(base)) != len(base):
            raise ValueError(
                "colors.neutral_province, colors.sea and colors.outside must be pairwise distinct"
            )
        return self
 
 
class StraitSettings(_Strict):
    default_crossing_multiplier: float = Field(
        ge=0.05,
        le=1.0,
        description="Доля обычной проходимости при переправе через узкий пролив.",
    )
 
 
class StartingGroupSettings(_Strict):
    require_connected: bool = Field(
        description="Стартовая группа провинций обязана быть связной (Bible §6).",
    )
 
 
class BigWindowSettings(_Strict):
    method: Literal["disabled", "fullscreen_api", "resize_window", "separate_window"] = Field(
        description="Способ режима большого окна; disabled скрывает кнопку «Развернуть».",
    )
    resize_target_width_px: int = Field(
        ge=630,
        le=1000,
        description="Целевая ширина окна для resize_window, px (границы платформы уточнить).",
    )
    resize_target_height_px: int = Field(
        ge=600,
        le=4050,
        description="Целевая высота окна для resize_window, px (границы платформы уточнить).",
    )
    pass_ttl_seconds: int = Field(
        ge=10,
        le=600,
        description="Срок действия одноразового пропуска для separate_window, сек.",
    )
 
 
class LimitsSettings(_Strict):
    max_nodes: int = Field(ge=100, le=20000)
    max_edges_per_node: int = Field(ge=4, le=100)
    max_geometry_bytes: int = Field(ge=100_000, le=20_000_000)
    max_manifest_bytes: int = Field(ge=100_000, le=20_000_000)
 
 
class AttributionSettings(_Strict):
    text: str = Field(
        min_length=1,
        max_length=300,
        description="Строка авторства исходной карты, показывается в клиенте.",
    )
 
 
class MapConfig(_Strict):
    """Корневая модель конфигурации модуля 01_map."""
 
    view: ViewSettings
    refresh: RefreshSettings
    colors: ColorSettings
    strait: StraitSettings
    starting_group: StartingGroupSettings
    big_window: BigWindowSettings
    limits: LimitsSettings
    attribution: AttributionSettings
 
    @classmethod
    def from_yaml(cls, path: str) -> "MapConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)
 
    @classmethod
    def get_default_config_path(cls) -> str:
        """
        Путь к configs/01_map.yaml, вычисляемый от расположения модуля,
        поэтому работает и из backend/src, и из backend/tests.
        """
        # Этот файл: backend/src/modules/_01_map/config_schema.py
        # Конфиг:    configs/01_map.yaml
        current_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        project_root = os.path.dirname(backend_dir)
        return os.path.join(project_root, "configs", "01_map.yaml")
 
 
if __name__ == "__main__":
    # Ручная проверка: python -m modules._01_map.config_schema
    config = MapConfig.from_yaml(MapConfig.get_default_config_path())
    print(config.model_dump_json(indent=2))
 