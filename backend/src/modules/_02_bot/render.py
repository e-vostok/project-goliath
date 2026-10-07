"""
Template rendering and value sanitizing of module 02_bot (Spec 3.6).

Substitution is deliberately NOT ``str.format``: only ``{name}``
placeholders matching the schema's regex are replaced, everything else
is literal text. Values pass :func:`sanitize_value` before they can
reach a message — control/invisible characters are dropped, whitespace
collapses, ``[``/``]`` become ``(``/``)`` so VK mention markup
(``[id1|name]``) cannot be smuggled in, and the result is truncated to
``limits.variable_max_length``.

Failures map to queue drop reasons: a missing variable raises
``TemplateError`` (``TEMPLATE_ERROR``), an oversize result raises
``MessageTooLong`` (``TOO_LONG``).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence

from modules._00_core.exceptions import CoreDomainError
from modules._02_bot.composer import ComposedMessage, RowView, _utc
from modules._02_bot.config_schema import _PLACEHOLDER_RE, BotConfig


class TemplateError(CoreDomainError):
    """A template placeholder has no matching variable."""

    def __init__(self, name: str):
        super().__init__(
            f"template variable '{name}' has no value", "TEMPLATE_ERROR"
        )


class MessageTooLong(CoreDomainError):
    """Rendered text exceeds limits.message_max_chars."""

    def __init__(self, length: int, limit: int):
        super().__init__(
            f"rendered message is {length} characters, "
            f"limit is {limit}",
            "TOO_LONG",
        )


def sanitize_value(value: object, max_length: int) -> str:
    """Spec 3.6 cleanup of one template variable, in order."""
    text = unicodedata.normalize("NFC", str(value))
    text = "".join(
        ch
        for ch in text
        if unicodedata.category(ch) not in ("Cc", "Cf")
    )
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("[", "(").replace("]", ")")
    if len(text) > max_length:
        text = text[: max_length - 1] + "…"
    return text


def render(template: str, variables: Mapping[str, object]) -> str:
    """
    Replace ``{name}`` placeholders only — every other character,
    including stray braces the schema never lets through anyway, stays
    literal. A placeholder with no variable raises TemplateError.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise TemplateError(name)
        return str(variables[name])

    return _PLACEHOLDER_RE.sub(_replace, template)


def _sanitized(payload: Mapping[str, object], config: BotConfig) -> dict:
    return {
        key: sanitize_value(value, config.limits.variable_max_length)
        for key, value in payload.items()
    }


def _newest(rows: Sequence[RowView]) -> RowView:
    """The freshest row of a group — source of batch/summary variables."""
    return max(rows, key=lambda r: (_utc(r.created_at), r.id))


def render_message(
    message: ComposedMessage,
    rows_by_id: Mapping[int, RowView],
    config: BotConfig,
) -> str:
    """Render one composed message to its final VK text."""
    mode = message.render_mode
    if mode == "SINGLE":
        row = rows_by_id[message.row_ids[0]]
        if row.kind == "REPLY":
            return render_reply(row, config, {})
        text = render(
            config.types[message.type_key].text,
            _sanitized(row.payload, config),
        )
    elif mode == "BATCH":
        rows = [rows_by_id[i] for i in message.row_ids]
        variables = _sanitized(_newest(rows).payload, config)
        variables["count"] = str(len(message.row_ids))
        text = render(config.types[message.type_key].batch_text, variables)
    elif mode == "SUMMARY":
        lines = []
        for type_key, collapsed_count in message.collapsed_counts:
            type_rows = [
                rows_by_id[i]
                for i in message.row_ids
                if rows_by_id[i].type_key == type_key
            ]
            variables = _sanitized(_newest(type_rows).payload, config)
            variables["count"] = str(collapsed_count)
            lines.append(render(config.types[type_key].line_text, variables))
        # Oldest lines are dropped first; the survivors keep their
        # oldest->newest order (Spec 3.4).
        text = "\n".join(lines[-config.limits.bundle_max_lines :])
    else:
        raise NotImplementedError(f"unknown render mode {mode!r}")

    if len(text) > config.limits.message_max_chars:
        raise MessageTooLong(len(text), config.limits.message_max_chars)
    return text


def render_reply(
    row: RowView,
    config: BotConfig,
    extra_vars: Mapping[str, object],
) -> str:
    """
    Render one ``REPLY`` row (Spec 3.9/5.5, Issue 3).

    ``payload.template`` names a ``dialog.texts`` template — an
    unknown name (or a ``payload.keyboard`` outside ``AUTO``/``HELP``)
    is a producer bug and maps to ``TEMPLATE_ERROR``. Variables come
    from ``payload.vars`` plus caller-supplied ``extra_vars`` and are
    sanitized like notification values (INV-B12).
    """
    payload = row.payload or {}
    template_name = payload.get("template")
    template = (
        getattr(config.dialog.texts, template_name, None)
        if isinstance(template_name, str)
        else None
    )
    if template is None:
        raise TemplateError(str(template_name))
    if payload.get("keyboard", "AUTO") not in ("AUTO", "HELP"):
        raise TemplateError("keyboard")

    variables: dict[str, object] = dict(payload.get("vars") or {})
    variables.update(extra_vars)
    text = render(template, _sanitized(variables, config))
    if len(text) > config.limits.message_max_chars:
        raise MessageTooLong(len(text), config.limits.message_max_chars)
    return text
