"""
Pydantic-схема валидации баланса модуля 00_core.

Загружает и валидирует configs/00_core.yaml при старте приложения и в CI
(pytest tests/test_configs_validity.py). Некорректный баланс обязан
прерывать запуск сервера до открытия первого соединения.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from modules._00_core.color_policy import oklab_distance

# Имя хоста в нижнем регистре, без схемы, порта и пути.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

# Цвет в формате #RRGGBB (регистр не важен: сервис приводит к верхнему).
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Идентификатор готового флага или портрета (он же имя файла без расширения).
_CATALOG_ID_RE = re.compile(r"^[a-z0-9_]{1,50}$")


def _check_hosts(field: str, hosts: list[str]) -> list[str]:
    """Хосты: нижний регистр, без схемы, порта и пути, без дублей."""
    for host in hosts:
        if _HOSTNAME_RE.match(host) is None:
            raise ValueError(
                f"{field}: '{host}' не является именем "
                "хоста в нижнем регистре без схемы, порта и пути"
            )
    if len(set(hosts)) != len(hosts):
        raise ValueError(f"{field}: дубли недопустимы")
    return hosts


class TickSettings(BaseModel):
    tick_time: str = Field(
        default="00:00",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="Локальное время суточного тика, строгий формат HH:MM (24ч).",
    )
    tick_timezone: str = Field(
        default="Europe/Moscow",
        description=(
            "IANA-зона, в которой задано tick_time (резолвится через zoneinfo)."
        ),
    )
    tick_interval_hours: int = Field(
        ge=1,
        le=168,
        description="Наследие: интервал для посева первого next_tick_at "
        "миграцией 0001 на свежей БД. Планировщик и тик его не используют — "
        "расписание задают tick_time + tick_timezone.",
    )
    retry_delay_seconds: int = Field(
        ge=1,
        le=3600,
        description="Пауза перед повторной попыткой тика после сбоя, секунды.",
    )
    heartbeat_interval_seconds: int = Field(
        ge=1,
        le=300,
        default=30,
        description="Шаг ожидания планировщика тиков, секунды: цикл спит "
        "не дольше этого интервала, перечитывает next_tick_at при каждом "
        "пробуждении и обновляет метку жизни для /api/v1/health.",
    )
    health_max_heartbeat_age_seconds: int = Field(
        ge=60,
        le=3600,
        default=180,
        description="Порог «живости» планировщика для /api/v1/health, "
        "секунды: метка старше порога даёт scheduler=stale. Обязан "
        "превышать retry_delay_seconds + heartbeat_interval_seconds — "
        "во время сбоя БД метка может отставать примерно на retry_delay.",
    )

    @field_validator("tick_timezone")
    @classmethod
    def check_timezone_resolves(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"tick_timezone '{v}' is not a resolvable IANA zone"
            ) from exc
        return v


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


class AdminPanelSettings(BaseModel):
    """Одноразовая ссылка и короткий сеанс панели администратора (0.11.0)."""

    link_ttl_seconds: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Время жизни одноразовой метки входа в панель, секунды "
        "(нужно только пережить открытие новой вкладки).",
    )
    session_ttl_minutes: int = Field(
        default=60,
        ge=5,
        le=240,
        description="Время жизни сеанса панели (короткий Bearer JWT), минуты.",
    )
    max_pending_links_per_player: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Максимум невостребованных одноразовых ссылок на одного "
        "игрока; сверх предела самая старая выбрасывается.",
    )
    audit_log_max_rows: int = Field(
        default=5000,
        ge=500,
        le=1000000,
        description="Предел записей журнала администратора "
        "(admin_audit_log): при каждой новой записи самые старые сверх "
        "предела удаляются автоматически.",
    )


class NationSettings(BaseModel):
    nation_name_min_length: int = Field(ge=1, le=10)
    nation_name_max_length: int = Field(ge=1, le=100)
    short_name_min_length: int = Field(
        ge=1,
        le=10,
        description="Минимальная длина краткого названия, символы.",
    )
    short_name_max_length: int = Field(
        ge=1,
        le=100,
        description="Максимальная длина краткого названия, символы "
        "(не больше длины колонки nations.short_name и не больше "
        "nation_name_max_length).",
    )
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
    leader_name_min_length: int = Field(
        ge=1,
        le=10,
        description="Минимальная длина имени лидера, символы.",
    )
    leader_name_max_length: int = Field(
        ge=1,
        le=100,
        description="Максимальная длина имени лидера, символы "
        "(не больше длины колонки nations.leader_name).",
    )
    leader_title_min_length: int = Field(
        ge=1,
        le=10,
        description="Минимальная длина должности лидера, символы.",
    )
    leader_title_max_length: int = Field(
        ge=1,
        le=100,
        description="Максимальная длина должности лидера, символы "
        "(не больше длины колонки nations.leader_title).",
    )
    motto_max_length: int = Field(
        ge=1,
        le=100,
        description="Максимальная длина девиза, символы "
        "(не больше длины колонки nations.motto). Поле необязательное.",
    )
    description_max_length: int = Field(
        ge=1,
        le=200,
        description="Максимальная длина краткого описания, символы "
        "(не больше длины колонки nations.description). Поле необязательное.",
    )
    leader_bio_max_length: int = Field(
        ge=1,
        le=2000,
        description="Максимальная длина биографии лидера, символы "
        "(не больше длины колонки nations.leader_bio). Поле необязательное.",
    )
    capital_name_min_length: int = Field(
        ge=1,
        le=10,
        description="Минимальная длина названия столицы, символы.",
    )
    capital_name_max_length: int = Field(
        ge=1,
        le=100,
        description="Максимальная длина названия столицы, символы "
        "(не больше длины колонки nations.capital_name).",
    )
    history_url_max_length: int = Field(
        ge=30,
        le=2000,
        description="Максимальная длина ссылки на историю государства, символы "
        "(не больше длины колонки nations.history_url).",
    )
    history_url_allowed_hosts: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Допустимые хосты ссылки на историю: нижний регистр, "
        "без схемы, порта и пути.",
    )
    anthem_url_max_length: int = Field(
        ge=30,
        le=2000,
        description="Максимальная длина ссылки на гимн, символы "
        "(не больше длины колонки nations.anthem_url). Поле необязательное.",
    )
    anthem_url_allowed_hosts: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Допустимые хосты ссылки на гимн: нижний регистр, "
        "без схемы, порта и пути.",
    )

    @field_validator("history_url_allowed_hosts")
    @classmethod
    def check_history_hosts(cls, hosts: list[str]) -> list[str]:
        return _check_hosts("history_url_allowed_hosts", hosts)

    @field_validator("anthem_url_allowed_hosts")
    @classmethod
    def check_anthem_hosts(cls, hosts: list[str]) -> list[str]:
        return _check_hosts("anthem_url_allowed_hosts", hosts)

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        if self.nation_name_min_length > self.nation_name_max_length:
            raise ValueError(
                "nation_name_min_length не может превышать nation_name_max_length"
            )
        if self.short_name_min_length > self.short_name_max_length:
            raise ValueError(
                "short_name_min_length не может превышать short_name_max_length"
            )
        if self.short_name_max_length > self.nation_name_max_length:
            raise ValueError(
                "short_name_max_length не может превышать nation_name_max_length"
            )
        if self.min_provinces_per_nation > self.max_provinces_per_nation:
            raise ValueError(
                "min_provinces_per_nation не может превышать max_provinces_per_nation"
            )
        if self.leader_name_min_length > self.leader_name_max_length:
            raise ValueError(
                "leader_name_min_length не может превышать leader_name_max_length"
            )
        if self.leader_title_min_length > self.leader_title_max_length:
            raise ValueError(
                "leader_title_min_length не может превышать leader_title_max_length"
            )
        if self.capital_name_min_length > self.capital_name_max_length:
            raise ValueError(
                "capital_name_min_length не может превышать capital_name_max_length"
            )
        return self


class ReservedColor(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=40,
        description="Название занятого картой цвета (попадает в текст ошибки).",
    )
    hex: str = Field(
        pattern=_HEX_RE.pattern,
        description="Цвет в формате #RRGGBB.",
    )


class ColorSettings(BaseModel):
    min_distance_nations: float = Field(
        ge=0.02,
        le=0.5,
        description="Минимальное расстояние OKLab между цветами двух "
        "государств (чёрный-белый = 1.0).",
    )
    min_distance_reserved: float = Field(
        ge=0.02,
        le=0.5,
        description="Минимальное расстояние OKLab между цветом государства "
        "и цветами, занятыми картой.",
    )
    reserved: list[ReservedColor] = Field(
        min_length=1,
        max_length=20,
        description="Цвета карты, которые не может занять государство.",
    )
    palette: list[str] = Field(
        min_length=1,
        max_length=60,
        description="Готовая палитра выбора цвета, #RRGGBB.",
    )

    @field_validator("palette")
    @classmethod
    def check_palette_format(cls, colors: list[str]) -> list[str]:
        for color in colors:
            if _HEX_RE.match(color) is None:
                raise ValueError(f"palette: '{color}' не в формате #RRGGBB")
        if len({c.upper() for c in colors}) != len(colors):
            raise ValueError("palette: дубли недопустимы")
        return colors

    @model_validator(mode="after")
    def check_palette_is_distinguishable(self) -> Self:
        """
        Палитра обязана быть пригодна «из коробки»: любые два её цвета
        различимы не хуже порога для государств, а любой её цвет — не хуже
        порога до цветов карты. Иначе игрок выбрал бы цвет, который сервер
        сразу отклонит.
        """
        palette = self.palette
        for i, first in enumerate(palette):
            for second in palette[i + 1 :]:
                if oklab_distance(first, second) < self.min_distance_nations:
                    raise ValueError(
                        f"palette: {first} и {second} ближе "
                        f"min_distance_nations ({self.min_distance_nations})"
                    )
            for reserved in self.reserved:
                if oklab_distance(first, reserved.hex) < self.min_distance_reserved:
                    raise ValueError(
                        f"palette: {first} ближе min_distance_reserved "
                        f"({self.min_distance_reserved}) к цвету карты "
                        f"«{reserved.name}» {reserved.hex}"
                    )
        return self


class CatalogSettings(BaseModel):
    flag_ids: list[str] = Field(
        max_length=200,
        description="Идентификаторы готовых флагов (имя файла без расширения).",
    )
    portrait_ids: list[str] = Field(
        max_length=200,
        description="Идентификаторы готовых портретов правителя.",
    )

    @field_validator("flag_ids", "portrait_ids")
    @classmethod
    def check_ids(cls, ids: list[str]) -> list[str]:
        for item in ids:
            if _CATALOG_ID_RE.match(item) is None:
                raise ValueError(
                    f"catalog: '{item}' не подходит: нужны строчная латиница, "
                    "цифры и «_», длина 1–50"
                )
        if len(set(ids)) != len(ids):
            raise ValueError("catalog: дубли недопустимы")
        return ids


class CalendarSettings(BaseModel):
    epoch_start_date: date
    months_per_turn: int = Field(
        ge=1,
        le=12,
        description="Количество игровых календарных месяцев, проходящих за один ход.",
    )
    month_names: list[Annotated[str, Field(min_length=1, max_length=20)]] = Field(
        min_length=12,
        max_length=12,
        description="Названия месяцев для формата «Месяц Год» "
        "(ровно 12, январь первым), без управляющих символов и дублей.",
    )

    @field_validator("month_names")
    @classmethod
    def check_month_names(cls, names: list[str]) -> list[str]:
        for name in names:
            if any(unicodedata.category(c) in ("Cc", "Cf") for c in name):
                raise ValueError(
                    f"month_names: '{name}' содержит управляющий или "
                    "невидимый символ (категории Cc/Cf недопустимы)"
                )
        if len(set(names)) != len(names):
            raise ValueError("month_names: дубли недопустимы")
        return names

    @model_validator(mode="after")
    def check_epoch_is_month_start(self) -> Self:
        if self.epoch_start_date.day != 1:
            raise ValueError("epoch_start_date обязан указывать на первое число месяца")
        return self


class CoreConfig(BaseModel):
    """Корневая модель конфигурации модуля 00_core."""

    tick: TickSettings
    auth: AuthSettings
    admin_panel: AdminPanelSettings
    nation: NationSettings
    color: ColorSettings
    catalog: CatalogSettings
    calendar: CalendarSettings

    @model_validator(mode="after")
    def check_health_threshold(self) -> Self:
        """
        health_max_heartbeat_age_seconds must exceed retry + heartbeat.

        During a DB outage the scheduler touches the heartbeat only once
        per retry cycle (retry_delay_seconds apart, paced by
        heartbeat_interval_seconds); a threshold at or below that sum
        would flap /api/v1/health to "stale" on a recoverable transient.
        """
        minimum = self.tick.retry_delay_seconds + self.tick.heartbeat_interval_seconds
        if self.tick.health_max_heartbeat_age_seconds <= minimum:
            raise ValueError(
                "tick.health_max_heartbeat_age_seconds "
                f"({self.tick.health_max_heartbeat_age_seconds}) must be "
                "greater than tick.retry_delay_seconds + "
                f"tick.heartbeat_interval_seconds ({minimum})"
            )
        return self

    @classmethod
    def from_yaml(cls, path: str) -> CoreConfig:
        with open(path, encoding="utf-8") as f:
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
