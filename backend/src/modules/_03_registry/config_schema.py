"""
Pydantic-схема валидации баланса и описания таблиц модуля 03_registry.

Загружает и валидирует configs/03_registry.yaml при старте приложения и в CI
(pytest tests/test_configs_validity.py). Некорректное значение обязано
прерывать запуск сервера до открытия первого соединения.

Как в 01_map и 02_bot, схема запрещает неизвестные ключи (extra="forbid"):
опечатка в имени ключа ломает запуск, а не молча игнорируется.

Описание таблиц — тоже часть конфига: администратор добавляет, убирает и
переупорядочивает столбцы правкой YAML (трек «А», без ТЗ). Поэтому схема
проверяет не только диапазоны, но и согласованность описания: какие фильтры
допустимы для типа столбца, существует ли столбец сортировки по умолчанию,
уникальны ли идентификаторы. Наличие поставщика данных для источников
(`tables[].source`, `columns[].source`) проверяет не схема, а запуск модуля
(Spec 2.5): схема не знает, какие модули подключены.
"""

from __future__ import annotations

import os
import re
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Идентификатор таблицы, столбца и источника: строчные латинские буквы,
# цифры, «_»; начинается с буквы.
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
# Управляющие символы и переводы строк в подписях запрещены.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# Версия API ВК: «5.199».
_API_VERSION_RE = re.compile(r"^5\.\d{1,3}$")
# Адрес API ВК: только https, без пути запроса и завершающей косой черты.
_API_BASE_URL_RE = re.compile(r"^https://[a-z0-9.-]+(?:/[a-z0-9._-]+)*$")

ColumnType = Literal[
    "index",     # порядковый номер: целое число
    "integer",   # целое число
    "text",      # строка
    "date",      # дата: {text, key}; key — целое число для сортировки и фильтра
    "person",    # аватарка и имя игрока
    "gauge",     # целое на знаковой шкале (судейский рейтинг)
    "flag",      # малый флаг: цвет-заглушка или изображение
    "nation",    # цветовая метка и название государства
]

FilterKind = Literal[
    "text",          # «содержит»
    "number_range",  # диапазон «от — до» по числу или ключу сортировки
    "date_range",    # диапазон календарных дат (по ключу сортировки — число дней)
    "presence",      # «есть / нет»
]

IconKey = Literal[
    "players", "nations", "map", "economy", "army", "diplomacy", "table",
]

# Какие фильтры допустимы для какого типа столбца. Пустой набор — фильтра нет.
ALLOWED_FILTERS: dict[str, frozenset[str]] = {
    "index": frozenset({"number_range"}),
    "integer": frozenset({"number_range"}),
    "text": frozenset({"text"}),
    "date": frozenset({"number_range", "date_range"}),
    "person": frozenset({"text"}),
    "gauge": frozenset({"number_range"}),
    "flag": frozenset(),
    "nation": frozenset({"text", "presence"}),
}

# Типы, которые можно искать общим полем поиска.
SEARCHABLE_TYPES: frozenset[str] = frozenset({"text", "person", "nation"})

# Типы, по которым нельзя сортировать (нет осмысленного порядка).
UNSORTABLE_TYPES: frozenset[str] = frozenset({"flag"})


class _Strict(BaseModel):
    """Базовый класс секций: неизвестные ключи запрещены."""

    model_config = ConfigDict(extra="forbid")


def _check_label(value: str, field: str) -> str:
    """Подпись: без управляющих символов, без краевых пробелов."""
    if _CONTROL_RE.search(value):
        raise ValueError(f"{field}: управляющие символы и переводы строк запрещены")
    if value != value.strip():
        raise ValueError(f"{field}: пробелы в начале и в конце запрещены")
    return value


# --------------------------------------------------------------------------
# Секции параметров
# --------------------------------------------------------------------------


class LayoutConfig(_Strict):
    """Раскладка окна «Реестр»."""

    # Положение ряда вкладок-иконок. Решение Project Owner 13.10.2026: сверху;
    # перенос вправо — смена одного значения.
    tabs_position: Literal["top", "right"]


class LimitsConfig(_Strict):
    """Пределы ответа."""

    # Предел строк одной таблицы в одном ответе; сверх предела клиент видит
    # первые строки по порядку по умолчанию и счётчик «Показано N из M».
    max_rows_per_table: int = Field(ge=50, le=10000)


class ProfilesConfig(_Strict):
    """Получение имён и малых аватарок профилей ВК (Spec 2.5, 3.4)."""

    # Главный выключатель. false — профили не запрашиваются, таблицы
    # показывают запасной вид.
    enabled: bool
    # Адрес API ВК и версия — как vk.api_base_url / vk.api_version в 02_bot.
    api_base_url: str
    api_version: str
    # Поле малой аватарки. Допустимые значения подтверждает REG-0.
    photo_field: Literal["photo_50", "photo_100"]
    # Срок годности сохранённого профиля, часы: после него профиль
    # запрашивается заново.
    ttl_hours: int = Field(ge=1, le=720)
    # Период пробуждения фоновой задачи, минуты.
    wake_interval_minutes: int = Field(ge=1, le=1440)
    # Число игроков в одном обращении к ВК (потолок метода уточняет REG-0).
    batch_size: int = Field(ge=1, le=1000)
    # Пауза между пакетами в одном цикле, секунды (0 — без паузы).
    batch_pause_seconds: int = Field(ge=0, le=60)
    # Предельное время ожидания ответа ВК, секунды.
    http_timeout_seconds: int = Field(ge=1, le=60)
    # Пауза перед повторной попыткой после неудачного обращения, минуты.
    failure_retry_minutes: int = Field(ge=1, le=1440)
    # Запасное имя, пока профиль не получен: ровно один плейсхолдер {number}.
    fallback_name_template: str = Field(min_length=3, max_length=60)

    @field_validator("api_base_url")
    @classmethod
    def _api_base_url_ok(cls, value: str) -> str:
        if not _API_BASE_URL_RE.fullmatch(value):
            raise ValueError(
                "api_base_url: ожидается https-адрес без завершающей косой черты, "
                "например https://api.vk.ru/method"
            )
        return value

    @field_validator("api_version")
    @classmethod
    def _api_version_ok(cls, value: str) -> str:
        if not _API_VERSION_RE.fullmatch(value):
            raise ValueError("api_version: ожидается вид 5.NNN")
        return value

    @field_validator("fallback_name_template")
    @classmethod
    def _fallback_ok(cls, value: str) -> str:
        _check_label(value, "fallback_name_template")
        rest = value.replace("{number}", "")
        if value.count("{number}") != 1 or "{" in rest or "}" in rest:
            raise ValueError(
                "fallback_name_template: должен содержать ровно один плейсхолдер "
                "{number} и никаких других фигурных скобок"
            )
        return value

    @model_validator(mode="after")
    def _intervals_consistent(self) -> Self:
        ttl_minutes = self.ttl_hours * 60
        if self.wake_interval_minutes > ttl_minutes:
            raise ValueError(
                "profiles.wake_interval_minutes не может превышать срок годности "
                "профиля profiles.ttl_hours (в минутах)"
            )
        if self.failure_retry_minutes > ttl_minutes:
            raise ValueError(
                "profiles.failure_retry_minutes не может превышать срок годности "
                "профиля profiles.ttl_hours (в минутах)"
            )
        return self


# --------------------------------------------------------------------------
# Описание таблиц
# --------------------------------------------------------------------------


class ColumnConfig(_Strict):
    """Один столбец таблицы."""

    id: str
    title: str = Field(min_length=1, max_length=40)
    type: ColumnType
    # Ключ значения в строке, которую отдаёт поставщик таблицы.
    source: str
    width_px: int = Field(ge=40, le=600)
    sortable: bool
    # Набор фильтров столбца; пустой список — фильтра нет.
    filters: list[FilterKind] = Field(max_length=4)
    # Подпись полей диапазона («Ход» вместо «от — до» по умолчанию), необязательна.
    filter_label: str | None = Field(default=None, min_length=1, max_length=20)
    # Участвует ли столбец в общем поле поиска.
    searchable: bool
    # Заглушка: столбец показывает временное значение (Bible, раздел 0).
    stub: bool
    # Границы шкалы: обязательны для gauge и запрещены для остальных типов.
    scale_min: int | None = Field(default=None, ge=-10000, le=10000)
    scale_max: int | None = Field(default=None, ge=-10000, le=10000)

    @field_validator("id", "source")
    @classmethod
    def _slug_ok(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError(
                "ожидается идентификатор: строчные латинские буквы, цифры и «_», "
                "начинается с буквы, от 2 до 30 символов"
            )
        return value

    @field_validator("title")
    @classmethod
    def _title_ok(cls, value: str) -> str:
        return _check_label(value, "title")

    @field_validator("filter_label")
    @classmethod
    def _filter_label_ok(cls, value: str | None) -> str | None:
        return None if value is None else _check_label(value, "filter_label")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        label = f"столбец «{self.id}»"
        # Фильтры: допустимы для типа, без повторов.
        if len(set(self.filters)) != len(self.filters):
            raise ValueError(f"{label}: фильтры не должны повторяться")
        allowed = ALLOWED_FILTERS[self.type]
        bad = [f for f in self.filters if f not in allowed]
        if bad:
            raise ValueError(
                f"{label}: фильтр {bad[0]!r} недопустим для типа {self.type!r}; "
                f"допустимы: {sorted(allowed) or 'никакие'}"
            )
        # Подпись диапазона имеет смысл только при диапазонном фильтре.
        if self.filter_label is not None and not (
            {"number_range", "date_range"} & set(self.filters)
        ):
            raise ValueError(
                f"{label}: filter_label задаётся только для столбца с "
                "фильтром number_range или date_range"
            )
        # Поиск.
        if self.searchable and self.type not in SEARCHABLE_TYPES:
            raise ValueError(
                f"{label}: searchable недопустим для типа {self.type!r}"
            )
        # Сортировка.
        if self.sortable and self.type in UNSORTABLE_TYPES:
            raise ValueError(
                f"{label}: сортировка недопустима для типа {self.type!r}"
            )
        # Шкала.
        if self.type == "gauge":
            if self.scale_min is None or self.scale_max is None:
                raise ValueError(
                    f"{label}: для типа gauge обязательны scale_min и scale_max"
                )
            if self.scale_min >= self.scale_max:
                raise ValueError(f"{label}: scale_min должен быть меньше scale_max")
        elif self.scale_min is not None or self.scale_max is not None:
            raise ValueError(
                f"{label}: scale_min и scale_max допустимы только для типа gauge"
            )
        return self


class DefaultSortConfig(_Strict):
    """Порядок строк таблицы по умолчанию."""

    column: str
    direction: Literal["asc", "desc"]


class TableConfig(_Strict):
    """Одна таблица (одна вкладка окна)."""

    id: str
    title: str = Field(min_length=1, max_length=40)
    icon: IconKey
    # Ключ поставщика строк, зарегистрированного модулем-владельцем данных.
    source: str
    # Надпись, когда в таблице нет ни одной строки.
    empty_text: str = Field(min_length=1, max_length=120)
    default_sort: DefaultSortConfig
    columns: list[ColumnConfig] = Field(min_length=1, max_length=20)

    @field_validator("id", "source")
    @classmethod
    def _slug_ok(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError(
                "ожидается идентификатор: строчные латинские буквы, цифры и «_», "
                "начинается с буквы, от 2 до 30 символов"
            )
        return value

    @field_validator("title", "empty_text")
    @classmethod
    def _text_ok(cls, value: str) -> str:
        return _check_label(value, "текст таблицы")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        label = f"таблица «{self.id}»"
        ids = [c.id for c in self.columns]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{label}: идентификаторы столбцов должны быть уникальны")
        by_id = {c.id: c for c in self.columns}
        sort_col = by_id.get(self.default_sort.column)
        if sort_col is None:
            raise ValueError(
                f"{label}: default_sort.column «{self.default_sort.column}» "
                "не найден среди столбцов"
            )
        if not sort_col.sortable:
            raise ValueError(
                f"{label}: столбец default_sort «{sort_col.id}» не помечен sortable"
            )
        return self


# --------------------------------------------------------------------------
# Корневая модель
# --------------------------------------------------------------------------


class RegistryConfig(_Strict):
    """Весь configs/03_registry.yaml."""

    layout: LayoutConfig
    limits: LimitsConfig
    profiles: ProfilesConfig
    tables: list[TableConfig] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _tables_unique(self) -> Self:
        ids = [t.id for t in self.tables]
        if len(set(ids)) != len(ids):
            raise ValueError("tables: идентификаторы таблиц должны быть уникальны")
        return self

    def table(self, table_id: str) -> TableConfig:
        """Таблица по идентификатору; KeyError, если такой нет."""
        for t in self.tables:
            if t.id == table_id:
                return t
        raise KeyError(table_id)

    @classmethod
    def from_yaml(cls, path: str) -> "RegistryConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)

    @classmethod
    def get_default_config_path(cls) -> str:
        """
        Путь к configs/03_registry.yaml, вычисляемый от расположения модуля,
        поэтому работает и из backend/src, и из backend/tests.
        """
        # Этот файл: backend/src/modules/_03_registry/config_schema.py
        # Конфиг:    configs/03_registry.yaml
        current_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        project_root = os.path.dirname(backend_dir)
        return os.path.join(project_root, "configs", "03_registry.yaml")
