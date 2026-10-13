"""
Tests for the VK message renderer (Spec 3.6, Appendix T: T15).

Sanitization order (NFC -> drop Cc/Cf -> collapse whitespace -> strip ->
bracket remap -> truncate with ellipsis), placeholder rendering that
never touches str.format, BATCH variables sourced from the newest row,
SUMMARY line ordering and bundle_max_lines, and the message_max_chars
guard.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from modules._02_bot.composer import ComposedMessage, RowView
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.render import (
    MessageTooLong,
    TemplateError,
    render,
    render_message,
    sanitize_value,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

_id_seq = 0


def _row(type_key: str, age_minutes: int, payload: dict) -> RowView:
    global _id_seq
    _id_seq += 1
    return RowView(
        id=_id_seq,
        type_key=type_key,
        kind="NOTIFICATION",
        priority="normal",
        counts_toward_cap=True,
        created_at=NOW - timedelta(minutes=age_minutes),
        not_before=NOW - timedelta(minutes=age_minutes),
        next_attempt_at=NOW - timedelta(minutes=age_minutes),
        expires_at=NOW + timedelta(hours=1),
        payload=payload,
    )


def _single(row: RowView) -> ComposedMessage:
    return ComposedMessage(
        row_ids=(row.id,),
        render_mode="SINGLE",
        type_key=row.type_key,
        counts_toward_cap=True,
    )


def _by_id(*rows: RowView) -> dict[int, RowView]:
    return {r.id: r for r in rows}


def _config_with_dispatch_vars() -> BotConfig:
    """Real YAML, but the dispatch batch carries {from_nation} so the
    test can see which source row fed the batch variables."""
    with open(
        BotConfig.get_default_config_path(), encoding="utf-8"
    ) as f:
        data = yaml.safe_load(f)
    data = copy.deepcopy(data)
    data["types"]["DIPLOMATIC_DISPATCH"]["batch_text"] = (
        "Депеши от «{from_nation}» и других: {count}."
    )
    return BotConfig.model_validate(data)


def _small_config(bot_config: BotConfig, **limit_overrides) -> BotConfig:
    """A copy of the real config with tightened limits."""
    return bot_config.model_copy(
        update={
            "limits": bot_config.limits.model_copy(
                update=limit_overrides
            )
        }
    )


class TestSanitize:
    def test_markup_control_zero_width_and_whitespace(self, bot_config):
        """T15: VK markup brackets are remapped, Cc/Cf dropped,
        whitespace collapsed."""
        dirty = "  [id1|Иван]\u200b\n\n  ушёл \t "
        assert sanitize_value(
            dirty, bot_config.limits.variable_max_length
        ) == "(id1|Иван) ушёл"

    def test_truncation_adds_ellipsis(self, bot_config):
        limit = bot_config.limits.variable_max_length
        out = sanitize_value("x" * (limit + 50), limit)
        assert len(out) == limit
        assert out.endswith("…")

    def test_int_and_none(self, bot_config):
        limit = bot_config.limits.variable_max_length
        assert sanitize_value(42, limit) == "42"
        assert sanitize_value(None, limit) == "None"


class TestRenderTemplate:
    def test_only_named_placeholders_replaced(self):
        """Text the placeholder regex cannot match stays literal —
        no str.format semantics."""
        out = render("{x} и {X} и {a b} и {}", {"x": "1"})
        assert out == "1 и {X} и {a b} и {}"

    def test_missing_variable_raises(self):
        with pytest.raises(TemplateError):
            render("A {x} {y}", {"x": "1"})


class TestRenderMessage:
    def test_single_uses_type_text(self, bot_config):
        row = _row(
            "RED_ALERT",
            5,
            {"event_text": "[id5|враг] у ворот"},
        )
        out = render_message(_single(row), _by_id(row), bot_config)
        assert out == (
            "БОЕВАЯ ТРЕВОГА. (id5|враг) у ворот "
            "Откройте кабинет правителя."
        )

    def test_batch_uses_newest_row_variables(self):
        config = _config_with_dispatch_vars()
        old = _row(
            "DIPLOMATIC_DISPATCH", 60, {"from_nation": "Старуха"}
        )
        new = _row(
            "DIPLOMATIC_DISPATCH", 5, {"from_nation": "Новик"}
        )
        message = ComposedMessage(
            row_ids=(old.id, new.id),
            render_mode="BATCH",
            type_key="DIPLOMATIC_DISPATCH",
            counts_toward_cap=True,
        )
        out = render_message(message, _by_id(old, new), config)
        assert out == "Депеши от «Новик» и других: 2."

    def test_summary_keeps_collapsed_counts_order(self, bot_config):
        """The composer emits collapsed_counts oldest-type-first; the
        renderer follows that order one line_text per type."""
        directive = _row(
            "DIRECTIVE_STATUS",
            100,
            {"directive_title": "Д", "status_text": "с"},
        )
        digest = _row(
            "TICK_DIGEST",
            50,
            {
                "turn": 1,
                "game_date": "г",
                "nation_name": "н",
                "province_count": 1,
                "next_tick_time": "т",
            },
        )
        dispatch = _row(
            "DIPLOMATIC_DISPATCH", 10, {"from_nation": "Н"}
        )
        message = ComposedMessage(
            row_ids=(directive.id, digest.id, dispatch.id),
            render_mode="SUMMARY",
            type_key=None,
            counts_toward_cap=True,
            collapsed_counts=(
                ("DIRECTIVE_STATUS", 3),
                ("TICK_DIGEST", 1),
                ("DIPLOMATIC_DISPATCH", 2),
            ),
        )
        out = render_message(
            message,
            _by_id(directive, digest, dispatch),
            bot_config,
        )
        assert out.split("\n") == [
            "Статусы директив: 3.",
            "Ход 1 завершён.",
            "Депеш: 2.",
        ]

    def test_summary_drops_oldest_lines_beyond_bundle(self, bot_config):
        config = _small_config(bot_config, bundle_max_lines=2)
        directive = _row(
            "DIRECTIVE_STATUS",
            100,
            {"directive_title": "Д", "status_text": "с"},
        )
        digest = _row(
            "TICK_DIGEST",
            50,
            {
                "turn": 1,
                "game_date": "г",
                "nation_name": "н",
                "province_count": 1,
                "next_tick_time": "т",
            },
        )
        dispatch = _row(
            "DIPLOMATIC_DISPATCH", 10, {"from_nation": "Н"}
        )
        message = ComposedMessage(
            row_ids=(directive.id, digest.id, dispatch.id),
            render_mode="SUMMARY",
            type_key=None,
            counts_toward_cap=True,
            collapsed_counts=(
                ("DIRECTIVE_STATUS", 1),
                ("TICK_DIGEST", 1),
                ("DIPLOMATIC_DISPATCH", 1),
            ),
        )
        out = render_message(
            message, _by_id(directive, digest, dispatch), config
        )
        # 3 lines > bundle 2: the oldest (directive) line is dropped.
        assert out.split("\n") == [
            "Ход 1 завершён.",
            "Депеш: 1.",
        ]

    def test_oversized_raises(self, bot_config):
        # event_text is truncated to variable_max_length=100, so the
        # ceiling must drop below ~144 chars for the guard to fire.
        config = _small_config(bot_config, message_max_chars=100)
        row = _row(
            "RED_ALERT", 1, {"event_text": "е" * 100}
        )
        with pytest.raises(MessageTooLong):
            render_message(_single(row), _by_id(row), config)
