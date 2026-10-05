"""
Pydantic-схема валидации баланса и текстов модуля 02_bot.

Загружает и валидирует configs/02_bot.yaml при старте приложения и в CI
(pytest tests/test_configs_validity.py). Некорректное значение обязано
прерывать запуск сервера до открытия первого соединения.

Как и в 01_map, схема запрещает неизвестные ключи (extra="forbid"):
опечатка в имени ключа ломает запуск, а не молча игнорируется.

Тексты уведомлений и ответов бота — тоже часть конфига (трек «А»:
правка текстов без ТЗ). Поэтому схема проверяет шаблоны: допустимы
только плейсхолдеры вида {имя} из списка, объявленного для типа,
а самый длинный возможный текст обязан помещаться в сообщение.
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from typing import Literal, Self
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Ключ типа уведомления: ЗАГЛАВНЫЕ латинские буквы, цифры, «_».
_TYPE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")
# Плейсхолдер шаблона: {имя}; других фигурных скобок в тексте быть не может.
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]{0,29})\}")
# Имя хоста в нижнем регистре, без схемы, порта и пути (как в 00_core).
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)

# Предел длины одного шаблона, символы (до подстановки).
TEMPLATE_MAX_CHARS = 1000

# Переменные, которые обязан передать модуль-владелец события, по типам,
# объявленным самим ботом (Spec, Часть 2). Типы будущих модулей добавляются
# через register_notification_type и проверяются при старте (Spec, 2.5).
BUILTIN_TYPE_VARIABLES: dict[str, frozenset[str]] = {
    "TICK_DIGEST": frozenset(
        {"turn", "game_date", "nation_name", "province_count", "next_tick_time"}
    ),
    "RED_ALERT": frozenset({"event_text"}),
    "DIPLOMATIC_DISPATCH": frozenset({"from_nation"}),
    "DIRECTIVE_STATUS": frozenset({"directive_title", "status_text"}),
    "DEADLINE_WARNING": frozenset({"hours_left"}),
}

# Дополнительная переменная в batch_text и line_text: число слитых событий.
IMPLICIT_MERGE_VARIABLES: frozenset[str] = frozenset({"count"})

# Переменные ответов бота в диалоге.
DIALOG_TEXT_VARIABLES: dict[str, frozenset[str]] = {
    "start_guest": frozenset(),
    "start_member": frozenset({"nation_name"}),
    "status": frozenset(
        {
            "nation_name",
            "leader_title",
            "leader_name",
            "province_count",
            "turn",
            "game_date",
            "next_tick_time",
        }
    ),
    "help": frozenset(),
    "plate": frozenset(),
}


class _Strict(BaseModel):
    """Базовый класс секций: неизвестные ключи запрещены."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# Проверка шаблонов
# --------------------------------------------------------------------------


def template_placeholders(text: str) -> list[str]:
    """Имена плейсхолдеров шаблона в порядке появления."""
    return _PLACEHOLDER_RE.findall(text)


def check_template(
    label: str,
    text: str,
    allowed: frozenset[str],
    *,
    variable_max_length: int,
    message_max_chars: int,
) -> None:
    """
    Проверка одного шаблона текста; ValueError с понятным сообщением.

    Правила: длина ≤ TEMPLATE_MAX_CHARS; нет управляющих символов (кроме
    перевода строки) и невидимых символов форматирования; все
    плейсхолдеры из списка allowed; никаких «лишних» фигурных скобок;
    худший случай (каждая переменная максимальной длины) помещается
    в message_max_chars.
    """
    if len(text) > TEMPLATE_MAX_CHARS:
        raise ValueError(
            f"{label}: длина шаблона {len(text)} превышает {TEMPLATE_MAX_CHARS}"
        )
    for ch in text:
        if ch == "\n":
            continue
        if unicodedata.category(ch) in ("Cc", "Cf"):
            raise ValueError(
                f"{label}: недопустимый управляющий или невидимый символ U+{ord(ch):04X}"
            )
    names = template_placeholders(text)
    unknown = sorted(set(names) - allowed)
    if unknown:
        raise ValueError(
            f"{label}: неизвестные переменные {unknown}; "
            f"допустимы: {sorted(allowed) or 'никаких'}"
        )
    leftover = _PLACEHOLDER_RE.sub("", text)
    if "{" in leftover or "}" in leftover:
        raise ValueError(
            f"{label}: фигурные скобки допустимы только в составе плейсхолдера {{имя}}"
        )
    worst = len(leftover) + len(names) * variable_max_length
    if worst > message_max_chars:
        raise ValueError(
            f"{label}: в худшем случае текст займёт {worst} символов, "
            f"предел limits.message_max_chars = {message_max_chars}"
        )


# --------------------------------------------------------------------------
# Секции
# --------------------------------------------------------------------------


class VkSettings(_Strict):
    api_base_url: str = Field(
        pattern=r"^https://[a-z0-9.-]+(/[A-Za-z0-9._~/-]*)?$",
        max_length=200,
        description="Базовый адрес методов VK API, только https, без завершающего «/».",
    )
    api_version: str = Field(
        pattern=r"^5\.\d{2,3}$",
        description="Версия VK API, закрепляется явно (Spec, приложение V).",
    )
    http_timeout_seconds: int = Field(
        ge=2,
        le=60,
        description="Общий таймаут одного запроса к ВК, сек.",
    )


class SenderSettings(_Strict):
    poll_interval_seconds: int = Field(
        ge=1,
        le=30,
        description="Пауза опроса очереди, если «звонок» не пришёл, сек.",
    )
    claim_batch_size: int = Field(
        ge=1,
        le=50,
        description="Сколько игроков с готовыми сообщениями берётся в работу за проход.",
    )
    concurrency: int = Field(
        ge=1,
        le=10,
        description="Сколько запросов к ВК одновременно в полёте.",
    )
    lease_seconds: int = Field(
        ge=30,
        le=900,
        description="Срок «аренды» взятых в работу строк; по истечении строка возвращается в очередь.",
    )
    max_requests_per_second: int = Field(
        ge=1,
        le=20,
        description="Потолок запросов к ВК в секунду (не выше лимита ВК для сообщества: 20, проверка BOT-0, V5).",
    )
    max_attempts: int = Field(
        ge=1,
        le=20,
        description="Максимум попыток отправки одного сообщения.",
    )
    backoff_base_seconds: int = Field(
        ge=1,
        le=600,
        description="Начальная пауза перед повтором, сек.",
    )
    backoff_cap_seconds: int = Field(
        ge=1,
        le=3600,
        description="Потолок паузы перед повтором, сек.",
    )
    backoff_jitter: float = Field(
        ge=0.0,
        le=1.0,
        description="Доля случайного разброса паузы (0.2 = до +20%).",
    )
    purge_after_days: int = Field(
        ge=1,
        le=90,
        description="Через сколько суток удаляются завершённые строки очереди и журнал событий ВК.",
    )

    @model_validator(mode="after")
    def check_backoff(self) -> Self:
        if self.backoff_base_seconds > self.backoff_cap_seconds:
            raise ValueError(
                "sender.backoff_base_seconds не может превышать sender.backoff_cap_seconds"
            )
        return self


class BreakerSettings(_Strict):
    window_seconds: int = Field(
        ge=30,
        le=3600,
        description="Окно подсчёта системных сбоев отправки, сек.",
    )
    min_attempts: int = Field(
        ge=3,
        le=100,
        description="Минимум попыток в окне, чтобы выключатель вообще мог сработать.",
    )
    failure_ratio: float = Field(
        gt=0.0,
        le=1.0,
        description="Доля системных сбоев в окне, при которой отправка останавливается.",
    )
    open_seconds: int = Field(
        ge=10,
        le=3600,
        description="На сколько секунд отправка останавливается при срабатывании.",
    )


class LimitsSettings(_Strict):
    daily_cap_normal: int = Field(
        ge=1,
        le=100,
        description="Потолок обычных сообщений игроку за скользящие 24 часа.",
    )
    bundle_max_lines: int = Field(
        ge=2,
        le=20,
        description="Максимум строк в сводном сообщении при превышении потолка.",
    )
    variable_max_length: int = Field(
        ge=20,
        le=500,
        description="Максимальная длина значения одной переменной после очистки, символы.",
    )
    message_max_chars: int = Field(
        ge=200,
        le=9000,
        description="Максимальная длина сообщения, символы (предел ВК — 9000).",
    )


class ConsentSettings(_Strict):
    required_for_registration: bool = Field(
        description="Регистрация государства требует разрешения на сообщения от сообщества (действует только при включённом боте).",
    )
    recheck_after_seconds: int = Field(
        ge=60,
        le=86400,
        description="Как долго результат проверки разрешения в ВК считается свежим, сек.",
    )
    refresh_min_interval_seconds: int = Field(
        ge=1,
        le=60,
        description="Минимальный интервал между принудительными проверками одного игрока, сек.",
    )
    reconcile_sweep_interval_seconds: int = Field(
        ge=60,
        le=86400,
        description="Как часто фон проверяет игроков с неизвестным разрешением, сек.",
    )
    reconcile_batch_size: int = Field(
        ge=1,
        le=100,
        description="Сколько игроков проверяется за один проход фоновой сверки.",
    )


class DeadlineSettings(_Strict):
    offset_minutes: int = Field(
        ge=15,
        le=720,
        description="За сколько минут до расчёта хода создаётся предупреждение о дедлайне.",
    )


class TypeSettings(_Strict):
    """Правила одного типа уведомления (каталог Bible, раздел 2)."""

    enabled: bool = Field(
        description="Выключенный тип не создаёт сообщений (постановка отклоняется как TYPE_DISABLED).",
    )
    priority: Literal["critical", "normal"] = Field(
        description="critical — вперёд очереди и мимо суточного потолка.",
    )
    requires_consent: bool = Field(
        description="Отправлять только при подтверждённом разрешении игрока.",
    )
    counts_toward_cap: bool = Field(
        description="Учитывается ли сообщение в суточном потолке limits.daily_cap_normal.",
    )
    ttl_minutes: int = Field(
        ge=1,
        le=10080,
        description="Срок годности с момента постановки, мин; позже сообщение не отправляется.",
    )
    hold_seconds: int = Field(
        ge=0,
        le=3600,
        description="Выдержка перед отправкой, чтобы близкие события успели слиться, сек.",
    )
    merge: Literal["never", "over_cap", "always"] = Field(
        description="never — не сливать; over_cap — сливать только сверх лимита окна; always — сливать всё готовое.",
    )
    max_per_window: int = Field(
        ge=0,
        le=100,
        description="Лимит сообщений этого типа игроку за окно; 0 — без лимита.",
    )
    window_minutes: int = Field(
        ge=1,
        le=10080,
        description="Длина окна лимита, мин.",
    )
    text: str = Field(min_length=1, description="Шаблон одного сообщения.")
    batch_text: str | None = Field(
        description="Шаблон слитого сообщения ({count} — число событий); обязателен при merge != never.",
    )
    line_text: str | None = Field(
        description="Строка сводного сообщения при превышении суточного потолка ({count}); обязательна при counts_toward_cap.",
    )

    @model_validator(mode="after")
    def check_rules(self) -> Self:
        if self.merge != "never" and self.batch_text is None:
            raise ValueError("batch_text обязателен при merge != never")
        if self.merge == "over_cap" and self.max_per_window < 2:
            raise ValueError("merge = over_cap требует max_per_window >= 2")
        if self.counts_toward_cap and self.line_text is None:
            raise ValueError("line_text обязателен при counts_toward_cap = true")
        if self.priority == "critical":
            if self.counts_toward_cap:
                raise ValueError(
                    "critical не может учитываться в суточном потолке (counts_toward_cap = true)"
                )
            if self.merge != "never":
                raise ValueError("critical не сливается (merge должен быть never)")
            if self.hold_seconds != 0:
                raise ValueError("critical не выдерживается (hold_seconds должен быть 0)")
        if self.hold_seconds >= self.ttl_minutes * 60:
            raise ValueError("hold_seconds должен быть меньше срока годности ttl_minutes")
        return self


class ButtonLabels(_Strict):
    status: str = Field(min_length=1, max_length=40)
    help: str = Field(min_length=1, max_length=40)
    register_nation: str = Field(min_length=1, max_length=40)
    rules: str = Field(min_length=1, max_length=40)
    regulations: str = Field(min_length=1, max_length=40)
    contact_admin: str = Field(min_length=1, max_length=40)


class DialogTexts(_Strict):
    start_guest: str = Field(min_length=1)
    start_member: str = Field(min_length=1)
    status: str = Field(min_length=1)
    help: str = Field(min_length=1)
    plate: str = Field(min_length=1)


class HelpLinks(_Strict):
    allowed_hosts: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Допустимые хосты ссылок кнопок помощи: нижний регистр, без схемы, порта и пути.",
    )
    rules_url: str | None = Field(description="Ссылка на правила; null — кнопка скрыта.")
    regulations_url: str | None = Field(description="Ссылка на регламент; null — кнопка скрыта.")
    admin_contact_url: str | None = Field(
        description="Ссылка «Связаться с администрацией»; null — кнопка скрыта.",
    )

    @field_validator("allowed_hosts")
    @classmethod
    def check_hosts(cls, hosts: list[str]) -> list[str]:
        for host in hosts:
            if _HOSTNAME_RE.match(host) is None:
                raise ValueError(
                    f"allowed_hosts: '{host}' не является именем хоста в нижнем регистре "
                    "без схемы, порта и пути"
                )
        if len(set(hosts)) != len(hosts):
            raise ValueError("allowed_hosts: дубли недопустимы")
        return hosts

    @model_validator(mode="after")
    def check_urls(self) -> Self:
        for name in ("rules_url", "regulations_url", "admin_contact_url"):
            url = getattr(self, name)
            if url is None:
                continue
            if len(url) > 300:
                raise ValueError(f"{name}: длина более 300 символов")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError(f"{name}: ссылка должна начинаться с https://")
            if parsed.hostname not in self.allowed_hosts:
                raise ValueError(
                    f"{name}: хост '{parsed.hostname}' не входит в allowed_hosts"
                )
        return self


class ClientSettings(_Strict):
    """Поведение окна согласия в приложении (Spec 5.6)."""

    chat_url_template: str = Field(
        min_length=10,
        max_length=200,
        description="Ссылка на диалог с сообществом; {group_id} заменяется числовым id сообщества. Хост — из dialog.help.allowed_hosts.",
    )
    consent_poll_interval_seconds: int = Field(
        ge=2,
        le=30,
        description="Как часто окно проверяет, что игрок разрешил сообщения, сек.",
    )
    consent_poll_timeout_seconds: int = Field(
        ge=10,
        le=600,
        description="Сколько секунд окно ждёт разрешения после открытия чата, затем показывает кнопку «Проверить».",
    )

    @model_validator(mode="after")
    def check_poll(self) -> Self:
        if self.consent_poll_timeout_seconds <= self.consent_poll_interval_seconds:
            raise ValueError(
                "client.consent_poll_timeout_seconds должен превышать client.consent_poll_interval_seconds"
            )
        return self


class DialogSettings(_Strict):
    plate_cooldown_minutes: int = Field(
        ge=1,
        le=1440,
        description="Не чаще одного раза за это время игроку отправляется плашка на свободный текст, мин.",
    )
    reply_ttl_minutes: int = Field(
        ge=1,
        le=60,
        description="Срок годности ответа бота в диалоге, мин.",
    )
    labels: ButtonLabels
    texts: DialogTexts
    help: HelpLinks


# --------------------------------------------------------------------------
# Корневая модель
# --------------------------------------------------------------------------


class BotConfig(_Strict):
    """Корневая модель конфигурации модуля 02_bot."""

    vk: VkSettings
    sender: SenderSettings
    breaker: BreakerSettings
    limits: LimitsSettings
    consent: ConsentSettings
    deadline: DeadlineSettings
    client: ClientSettings
    dialog: DialogSettings
    types: dict[str, TypeSettings]

    @field_validator("types")
    @classmethod
    def check_type_keys(cls, types: dict[str, TypeSettings]) -> dict[str, TypeSettings]:
        for key in types:
            if _TYPE_KEY_RE.match(key) is None:
                raise ValueError(
                    f"types: ключ '{key}' должен состоять из заглавных латинских букв, цифр и «_» "
                    "(3–40 символов, начинается с буквы)"
                )
        missing = sorted(set(BUILTIN_TYPE_VARIABLES) - set(types))
        if missing:
            raise ValueError(f"types: отсутствуют обязательные типы {missing}")
        return types

    @model_validator(mode="after")
    def check_cross_rules(self) -> Self:
        # 1. Аренда строк покрывает худший случай отправки партии.
        worst_batch = math.ceil(self.sender.claim_batch_size / self.sender.concurrency)
        if self.sender.lease_seconds <= worst_batch * self.vk.http_timeout_seconds:
            raise ValueError(
                "sender.lease_seconds должен быть больше "
                "ceil(claim_batch_size / concurrency) * vk.http_timeout_seconds "
                f"({worst_batch * self.vk.http_timeout_seconds})"
            )

        # 2. Предупреждение о дедлайне не живёт дольше времени до хода.
        deadline = self.types["DEADLINE_WARNING"]
        if deadline.ttl_minutes > self.deadline.offset_minutes:
            raise ValueError(
                "types.DEADLINE_WARNING.ttl_minutes не может превышать deadline.offset_minutes"
            )

        # 2а. Ссылка на диалог с сообществом: https, один {group_id}, хост разрешён.
        tpl = self.client.chat_url_template
        if tpl.count("{group_id}") != 1:
            raise ValueError("client.chat_url_template должен содержать ровно один {group_id}")
        probe = tpl.replace("{group_id}", "1")
        if "{" in probe or "}" in probe:
            raise ValueError("client.chat_url_template: других фигурных скобок быть не должно")
        parsed_chat = urlparse(probe)
        if parsed_chat.scheme != "https" or not parsed_chat.hostname:
            raise ValueError("client.chat_url_template должен начинаться с https://")
        if parsed_chat.hostname not in self.dialog.help.allowed_hosts:
            raise ValueError(
                f"client.chat_url_template: хост '{parsed_chat.hostname}' не входит в dialog.help.allowed_hosts"
            )

        # 3. Шаблоны типов: переменные и худшая длина.
        v_max = self.limits.variable_max_length
        m_max = self.limits.message_max_chars
        for key, t in self.types.items():
            base = BUILTIN_TYPE_VARIABLES.get(key)
            if base is None:
                # Тип модуля-сателлита: набор переменных проверит запуск
                # по реестру (Spec 2.5); здесь — только форма шаблона.
                continue
            check_template(
                f"types.{key}.text", t.text, base,
                variable_max_length=v_max, message_max_chars=m_max,
            )
            merged = base | IMPLICIT_MERGE_VARIABLES
            if t.batch_text is not None:
                check_template(
                    f"types.{key}.batch_text", t.batch_text, merged,
                    variable_max_length=v_max, message_max_chars=m_max,
                )
            if t.line_text is not None:
                check_template(
                    f"types.{key}.line_text", t.line_text, merged,
                    variable_max_length=v_max, message_max_chars=m_max,
                )

        # 4. Шаблоны ответов в диалоге.
        for name, allowed in DIALOG_TEXT_VARIABLES.items():
            check_template(
                f"dialog.texts.{name}", getattr(self.dialog.texts, name), allowed,
                variable_max_length=v_max, message_max_chars=m_max,
            )

        # 5. Сводное сообщение (суточный потолок) помещается в сообщение.
        longest_line = 0
        for key, t in self.types.items():
            if t.line_text is not None:
                names = template_placeholders(t.line_text)
                longest_line = max(
                    longest_line,
                    len(_PLACEHOLDER_RE.sub("", t.line_text)) + len(names) * v_max,
                )
        if (longest_line + 4) * self.limits.bundle_max_lines > m_max:
            raise ValueError(
                "limits.bundle_max_lines строк самой длинной line_text не помещаются в "
                f"limits.message_max_chars ({m_max})"
            )
        return self

    @classmethod
    def from_yaml(cls, path: str) -> "BotConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)

    @classmethod
    def get_default_config_path(cls) -> str:
        """
        Путь к configs/02_bot.yaml, вычисляемый от расположения модуля,
        поэтому работает и из backend/src, и из backend/tests.
        """
        # Этот файл: backend/src/modules/_02_bot/config_schema.py
        # Конфиг:    configs/02_bot.yaml
        current_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        project_root = os.path.dirname(backend_dir)
        return os.path.join(project_root, "configs", "02_bot.yaml")


if __name__ == "__main__":
    # Ручная проверка: python -m modules._02_bot.config_schema
    config = BotConfig.from_yaml(BotConfig.get_default_config_path())
    print(config.model_dump_json(indent=2))
