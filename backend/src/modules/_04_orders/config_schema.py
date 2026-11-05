"""
Pydantic-схема валидации баланса модуля 04_orders («Приказы»).

Загружает и валидирует configs/04_orders.yaml при старте приложения и в CI
(pytest tests/test_configs_validity.py). Некорректное значение обязано
прерывать запуск сервера до открытия первого соединения.

Как в 01_map, 02_bot и 03_registry, схема запрещает неизвестные ключи
(extra="forbid"): опечатка в имени ключа ломает запуск, а не молча
игнорируется.

Домены ссылок на статьи ВК в этом конфиге не повторяются: правило «те же
домены, что у history_url» обеспечивает 00_core (nation.history_url_allowed_hosts).
Тексты уведомлений бота живут в configs/02_bot.yaml.
"""

from __future__ import annotations

import os
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

# Длины колонок таблицы orders (Spec 04_orders, Часть 1). Верхние границы
# текстовых лимитов не могут быть больше: любое валидное значение конфига
# обязано помещаться в колонку без новой миграции. Совпадение с моделью
# проверяет тест.
TITLE_COLUMN_LENGTH = 200
SUMMARY_COLUMN_LENGTH = 2000
URL_COLUMN_LENGTH = 2000


class _Strict(BaseModel):
    """Базовый класс секций: неизвестные ключи запрещены."""

    model_config = ConfigDict(extra="forbid")


class JudgeSettings(_Strict):
    """Судья: нагрузка, достижимость, срок (Bible, 2.2, 2.5, 2.7)."""

    max_pending_verdicts: int = Field(
        ge=1,
        le=50,
        description="Предел приказов, ожидающих вердикта, у одного судьи.",
    )
    require_reachable: StrictBool = Field(
        description=(
            "Судьёй может стать только достижимый игрок: владелец государства "
            "или игрок с согласием на сообщения бота."
        ),
    )
    verdict_deadline_hours: int = Field(
        ge=1,
        le=720,
        description="Срок на вердикт с момента назначения судьи, часы.",
    )
    reminder_percent: int = Field(
        ge=10,
        le=95,
        description=(
            "Доля срока, по прошествии которой судье уходит напоминание, процент."
        ),
    )

    @property
    def deadline_seconds(self) -> int:
        """Срок на вердикт, секунды."""
        return self.verdict_deadline_hours * 3600

    @property
    def reminder_seconds(self) -> int:
        """
        Смещение напоминания от момента назначения, секунды.

        Целочисленная арифметика (проценты, а не доля с плавающей точкой):
        результат точный и воспроизводимый.
        """
        return self.deadline_seconds * self.reminder_percent // 100


class RefusalSettings(_Strict):
    """
    Отказ судьи от назначенного приказа: штрафы рейтинга и окно
    повышенного штрафа (0.14.0, единица 7a).
    """

    penalty: int = Field(
        ge=1,
        le=50,
        description="Штраф рейтинга за отказ от назначенного приказа.",
    )
    penalty_late: int = Field(
        ge=1,
        le=50,
        description=(
            "Штраф рейтинга за отказ в последние late_window_hours срока."
        ),
    )
    late_window_hours: int = Field(
        ge=1,
        description=(
            "Последние столько часов срока отказ стоит дороже; не может "
            "превышать judge.verdict_deadline_hours (проверяется на корне)."
        ),
    )

    @model_validator(mode="after")
    def check_late_not_below(self) -> Self:
        if self.penalty_late < self.penalty:
            raise ValueError(
                "refusal.penalty_late не может быть меньше refusal.penalty: "
                "отказ в последние часы срока штрафуется не мягче обычного"
            )
        return self


class AuthorSettings(_Strict):
    """Автор: предел неразрешённых приказов (Spec, D14, INV-O15)."""

    max_unresolved_orders: int = Field(
        ge=1,
        le=50,
        description=(
            "Предел приказов без вердикта у одного автора: ожидающих судью, "
            "распределённых и просроченных."
        ),
    )


class DistributionSettings(_Strict):
    """Фоновая задача: повтор распределения и напоминания (Bible, 2.3, 2.5)."""

    retry_interval_seconds: int = Field(
        ge=10,
        le=3600,
        description="Период прохода фоновой задачи, секунды.",
    )
    batch_size: int = Field(
        ge=1,
        le=500,
        description="Сколько приказов без судьи обрабатывается за один проход.",
    )


class LimitsSettings(_Strict):
    """Пределы текстовых полей приказа и вердикта (общие для обоих)."""

    title_min_length: int = Field(
        ge=1, le=20, description="Минимальная длина названия, символы."
    )
    title_max_length: int = Field(
        ge=1,
        le=TITLE_COLUMN_LENGTH,
        description="Максимальная длина названия, символы (не больше длины колонки).",
    )
    summary_min_length: int = Field(
        ge=1, le=100, description="Минимальная длина краткой сути, символы."
    )
    summary_max_length: int = Field(
        ge=1,
        le=SUMMARY_COLUMN_LENGTH,
        description=(
            "Максимальная длина краткой сути, символы (не больше длины колонки)."
        ),
    )
    url_max_length: int = Field(
        ge=30,
        le=URL_COLUMN_LENGTH,
        description=(
            "Максимальная длина ссылки на статью, символы (не больше длины колонки)."
        ),
    )

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        if self.title_min_length > self.title_max_length:
            raise ValueError("title_min_length не может превышать title_max_length")
        if self.summary_min_length > self.summary_max_length:
            raise ValueError("summary_min_length не может превышать summary_max_length")
        return self


class OrdersConfig(_Strict):
    """Корневая модель конфигурации модуля 04_orders."""

    judge: JudgeSettings
    refusal: RefusalSettings
    author: AuthorSettings
    distribution: DistributionSettings
    limits: LimitsSettings

    @model_validator(mode="after")
    def check_reminder_is_timely(self) -> Self:
        """
        Напоминание не должно опаздывать за срок.

        Фоновая задача проверяет напоминания раз в retry_interval_seconds, поэтому
        промежуток между моментом напоминания и концом срока обязан вмещать
        как минимум два прохода: иначе «срок истекает через N ч» придёт после
        истечения срока.
        """
        gap = self.judge.deadline_seconds - self.judge.reminder_seconds
        if self.distribution.retry_interval_seconds * 2 > gap:
            raise ValueError(
                "distribution.retry_interval_seconds, умноженный на 2, не "
                "может превышать промежуток между напоминанием и концом срока "
                f"({gap} с): уменьшите период задачи, увеличьте срок "
                "или уменьшите reminder_percent"
            )
        if self.refusal.late_window_hours > self.judge.verdict_deadline_hours:
            raise ValueError(
                "refusal.late_window_hours не может превышать "
                "judge.verdict_deadline_hours: окно повышенного штрафа "
                "шире самого срока"
            )
        return self

    @classmethod
    def from_yaml(cls, path: str) -> OrdersConfig:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)

    @classmethod
    def get_default_config_path(cls) -> str:
        """
        Путь к configs/04_orders.yaml, вычисляемый от расположения модуля,
        поэтому работает и из backend/src, и из backend/tests.
        """
        # Этот файл: backend/src/modules/_04_orders/config_schema.py
        # Конфиг:    configs/04_orders.yaml
        current_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        project_root = os.path.dirname(backend_dir)
        return os.path.join(project_root, "configs", "04_orders.yaml")
