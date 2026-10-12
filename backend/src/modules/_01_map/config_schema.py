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


class FrameConfig(_Strict):
    """Рамка предела отдаления в единицах ``view_box`` (Spec 3.8)."""

    x: float = Field(
        ge=0.0,
        description="Левый край рамки, ед. view_box.",
    )
    y: float = Field(
        ge=0.0,
        description="Верхний край рамки, ед. view_box.",
    )
    width: float = Field(
        gt=0.0,
        description="Ширина рамки, ед. view_box.",
    )
    height: float = Field(
        gt=0.0,
        description="Высота рамки, ед. view_box.",
    )


class ViewSettings(_Strict):
    frame: FrameConfig = Field(
        description="Рамка вида при минимальном масштабе; целиком внутри view_box манифеста (проверяет загрузчик).",
    )
    zoom_max: float = Field(
        ge=2.0,
        le=40.0,
        description="Максимальный масштаб относительно минимального (вид рамки по высоте окна).",
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
    inland_water: str = Field(pattern=_HEX_COLOR_RE.pattern)
    province_border: str = Field(pattern=_HEX_COLOR_RE.pattern)
    land_underlay: str = Field(
        pattern=_HEX_COLOR_RE.pattern,
        description="Подложка под заливки суши (map2_13): волосяные швы между соседними провинциями показывают цвет суши, а не моря.",
    )
    hover: str = Field(pattern=_HEX_COLOR_RE.pattern)

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


class HoverSettings(_Strict):
    """Подсветка узла при наведении (map2_0): заливка ``colors.hover``."""

    fill_opacity: float = Field(
        ge=0.0,
        le=0.6,
        description="Прозрачность заливки цветом colors.hover при наведении; 0 — без заливки.",
    )
    stroke_enabled: bool = Field(
        description="Обводить ли контур узла при наведении цветом colors.hover.",
    )


class BordersSettings(_Strict):
    """Слой границ (map2_4, map2_13): три собранных пути из
    ``borders.json`` — тонкая сплошная линия внутри государства,
    сплошная граница государства по суше и тонкая линия берега.
    Ширины — экранные px (non-scaling-stroke)."""

    internal_width: float = Field(
        ge=0.1,
        le=6.0,
        description="Толщина сплошной линии внутренних границ, px.",
    )
    internal_opacity: float = Field(
        ge=0.0,
        le=1.0,
        description="Прозрачность внутренних границ.",
    )
    internal_color: str = Field(pattern=_HEX_COLOR_RE.pattern)
    state_width: float = Field(
        ge=0.1,
        le=6.0,
        description="Толщина сплошной линии границы государства (только суша), px.",
    )
    state_color: str = Field(pattern=_HEX_COLOR_RE.pattern)
    coast_width: float = Field(
        ge=0.1,
        le=6.0,
        description="Толщина тонкой линии берега, px.",
    )
    coast_color: str = Field(pattern=_HEX_COLOR_RE.pattern)


class SelectionSettings(_Strict):
    """Подсветка выбора (map2_4): белая заливка цвета ``colors.hover``.
    Осматриваемая провинция пульсирует, отобранные в пикере светятся
    постоянно."""

    pulse_min_opacity: float = Field(
        ge=0.0,
        le=1.0,
        description="Нижняя прозрачность пульсации выбранной провинции.",
    )
    pulse_max_opacity: float = Field(
        ge=0.0,
        le=1.0,
        description="Верхняя прозрачность пульсации выбранной провинции.",
    )
    pulse_period_s: float = Field(
        ge=0.5,
        le=10.0,
        description="Период пульсации выбранной провинции, сек.",
    )
    picked_opacity: float = Field(
        ge=0.0,
        le=1.0,
        description="Постоянная прозрачность отобранных в пикере провинций.",
    )

    @model_validator(mode="after")
    def check_pulse_range(self) -> Self:
        if self.pulse_min_opacity > self.pulse_max_opacity:
            raise ValueError(
                "selection.pulse_min_opacity must not exceed pulse_max_opacity"
            )
        return self


class LabelsSettings(_Strict):
    """Подписи узлов (map2_6): название рисуется, только если помещается
    в свой ``label``-бокс на текущем масштабе; столкновения снимаются по
    приоритету площади. Шрифт — один из встроенных файлов клиента."""

    font: Literal[
        "fira_sans_condensed", "pt_sans_narrow", "roboto_condensed"
    ] = Field(
        description="Один из трёх встроенных шрифтов (SIL OFL, WOFF2 в клиенте).",
    )
    land_min_px: int = Field(
        ge=6,
        le=14,
        description="Подпись суши скрывается ниже этого размера шрифта, px.",
    )
    land_max_px: int = Field(
        ge=9,
        le=30,
        description="Максимальный размер подписи суши, px.",
    )
    sea_min_px: int = Field(
        ge=6,
        le=14,
        description="Подпись морской зоны скрывается ниже этого размера, px.",
    )
    sea_max_px: int = Field(
        ge=9,
        le=30,
        description="Максимальный размер подписи морской зоны, px.",
    )
    fit_ratio: float = Field(
        ge=0.5,
        le=1.0,
        description="Текст должен быть не шире и не выше этой доли label-бокса на экране.",
    )
    collision_padding_px: float = Field(
        ge=0.0,
        le=10.0,
        description="Прозрачный отступ вокруг подписи при проверке столкновений, px.",
    )
    halo_width_px: float = Field(
        ge=0.0,
        le=8.0,
        description="Толщина тёмного обвода (halo) вокруг букв, px.",
    )
    halo_color: str = Field(pattern=_HEX_COLOR_RE.pattern)
    land_color: str = Field(pattern=_HEX_COLOR_RE.pattern)
    sea_color: str = Field(pattern=_HEX_COLOR_RE.pattern)
    sea_letter_spacing_em: float = Field(
        ge=0.0,
        le=0.3,
        description="Разрежение букв морских подписей, em.",
    )
    province_zoom_ratio: float = Field(
        ge=0.5,
        le=1.0,
        description="Доля максимального зума камеры, с которой считается «максимальный зум» "
        "для подписей провинций (map2_6c): ниже — только морские подписи, на максимуме — только провинции.",
    )
    fade_ms: int = Field(
        ge=0,
        le=500,
        description="Длительность появления/исчезновения подписи, мс (map2_6c; 0 = без перехода).",
    )

    @model_validator(mode="after")
    def check_min_max(self) -> Self:
        if self.land_min_px > self.land_max_px:
            raise ValueError(
                "labels.land_min_px must not exceed labels.land_max_px"
            )
        if self.sea_min_px > self.sea_max_px:
            raise ValueError(
                "labels.sea_min_px must not exceed labels.sea_max_px"
            )
        return self


class StraitSettings(_Strict):
    default_crossing_multiplier: float = Field(
        ge=0.05,
        le=1.0,
        description="Доля обычной проходимости при переправе через узкий пролив.",
    )


class ReliefSettings(_Strict):
    """Подложка рельефа под картой (map2_16): две картинки Natural
    Earth — светлая под игровыми провинциями, почти чёрный неигровой
    мир вокруг, без плавных переходов и обрезов."""

    enabled: bool = Field(
        description="Слой включён; false — карта выглядит как раньше.",
    )
    strength_playable: float = Field(
        ge=0.0,
        le=1.0,
        description="Сила просвечивания рельефа сквозь заливки провинций (multiply).",
    )
    inactive_brightness: float = Field(
        ge=0.02,
        le=1.0,
        description="Яркость рельефа неигрового мира; целевое — блики не светлее #2A2A2A.",
    )


class StartingGroupSettings(_Strict):
    require_connected: bool = Field(
        description="Стартовая группа провинций обязана быть связной (Bible §6).",
    )


class BigWindowSettings(_Strict):
    enabled: bool = Field(
        description="Показывать кнопку «Развернуть» (полноэкранный режим страницы, проверено в ВК в E1).",
    )


class LimitsSettings(_Strict):
    max_nodes: int = Field(ge=100, le=20000)
    max_edges_per_node: int = Field(ge=4, le=100)
    max_geometry_bytes: int = Field(ge=100_000, le=20_000_000)
    max_manifest_bytes: int = Field(ge=100_000, le=20_000_000)
    max_borders_bytes: int = Field(ge=100_000, le=5_000_000)


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
    hover: HoverSettings
    borders: BordersSettings
    selection: SelectionSettings
    strait: StraitSettings
    relief: ReliefSettings
    labels: LabelsSettings
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
