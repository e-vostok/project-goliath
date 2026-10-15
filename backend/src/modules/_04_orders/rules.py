"""
Pure validation rules for the order and verdict text fields (Spec 2.5).

No DB access and no state: each function takes the raw input plus the
loaded ``OrdersConfig``, returns the normalized value to store, and
raises the matching module error on the first violated rule — the same
contract ``_00_core/profile_rules.py`` keeps for the nation profile.

``validate_article_url`` is a thin wrapper over the shared
``validate_vk_article_url`` (Spec D7): the orders module passes its own
length limit and the allowed-hosts snapshot the caller read once at
startup — the shared function raises the core ``HistoryUrlInvalidError``,
which is translated here into ``OrderUrlInvalidError`` with a Russian,
player-facing reason.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection

from modules._00_core.exceptions import HistoryUrlInvalidError
from modules._00_core.profile_rules import validate_vk_article_url
from modules._04_orders.config_schema import OrdersConfig
from modules._04_orders.exceptions import (
    OrderSummaryInvalidError,
    OrderTitleInvalidError,
    OrderUrlInvalidError,
)

# Unicode categories banned from order text (Spec 2.5): control (Cc —
# with the sole exception of "\n" inside the summary), format (Cf),
# surrogate (Cs), private use (Co) and unassigned (Cn).
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})

# Player-facing translations of the shared checker's failure reasons —
# keyed by a stable substring of the English reason the core raises.
_URL_REASON_RU = (
    ("scheme must be https", "ссылка должна начинаться с https://"),
    ("host is not in the allowed list", "адрес ссылки не разрешён"),
    ("port or userinfo", "в ссылке не должно быть порта или логина"),
    ("path must look like", "ссылка должна вести на статью ВК вида vk.com/@название"),
    ("cannot be parsed", "ссылку не удалось разобрать"),
    ("whitespace", "в ссылке не должно быть пробелов и служебных символов"),
)


def validate_title(value: str, config: OrdersConfig) -> str:
    """Normalize and check the order/verdict title; returns the stored text."""
    limits = config.limits
    text = value.strip()
    if not (limits.title_min_length <= len(text) <= limits.title_max_length):
        raise OrderTitleInvalidError(
            f"должно быть от {limits.title_min_length} до "
            f"{limits.title_max_length} символов, сейчас {len(text)}"
        )
    if "\n" in text or "\r" in text:
        raise OrderTitleInvalidError("название должно быть в одну строку")
    if any(
        unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in text
    ):
        raise OrderTitleInvalidError("содержит недопустимые символы")
    return text


def validate_summary(value: str, config: OrdersConfig) -> str:
    """
    Normalize and check the order/verdict summary.

    Newlines are normalized to ``\\n`` before the length check; a value
    that is empty after stripping fails the minimum length like any
    other too-short input.
    """
    limits = config.limits
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not (limits.summary_min_length <= len(text) <= limits.summary_max_length):
        raise OrderSummaryInvalidError(
            f"должна быть от {limits.summary_min_length} до "
            f"{limits.summary_max_length} символов, сейчас {len(text)}"
        )
    if any(
        ch != "\n" and unicodedata.category(ch) in _FORBIDDEN_CATEGORIES
        for ch in text
    ):
        raise OrderSummaryInvalidError("содержит недопустимые символы")
    return text


def validate_article_url(
    value: str,
    config: OrdersConfig,
    *,
    allowed_hosts: Collection[str],
) -> str:
    """
    Check the VK-article link (Spec D7): https scheme, a host from
    ``allowed_hosts`` (the ``nation.history_url_allowed_hosts`` list),
    a ``/@slug`` path, no query/fragment, length within
    ``limits.url_max_length``. Returns the stripped input.
    """
    url = value.strip()
    max_length = config.limits.url_max_length
    if len(url) > max_length:
        raise OrderUrlInvalidError(
            f"длиннее {max_length} символов, сейчас {len(url)}"
        )
    try:
        return validate_vk_article_url(
            url,
            max_length=max_length,
            allowed_hosts=allowed_hosts,
        )
    except HistoryUrlInvalidError as exc:
        message = exc.message
        reason = next(
            (ru for needle, ru in _URL_REASON_RU if needle in message),
            "ссылка должна вести на статью ВК вида vk.com/@название",
        )
        raise OrderUrlInvalidError(reason) from exc
