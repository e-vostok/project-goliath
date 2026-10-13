"""
Tests for the message composer (Spec 3.4, Appendix T: T4, T5, T6, T12).

Pure functions over RowView/SentHistory — no DB. Covers the daily cap
collapse to SUMMARY, over_cap window batching with the one-batch-per-
window deferral, merge=always, critical/REPLY head-of-queue behavior,
expiry/readiness filtering and the a=0 shutout.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules._02_bot.composer import (
    ComposedMessage,
    ComposeResult,
    RowView,
    SentHistory,
    compose,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

_id_seq = 0


def _row(
    type_key: str = "TICK_DIGEST",
    *,
    kind: str = "NOTIFICATION",
    priority: str = "normal",
    counts_toward_cap: bool = True,
    age_minutes: int = 0,
    not_before_minutes: int = -1,
    expires_minutes: int = 60,
    payload: dict | None = None,
) -> RowView:
    """A ready row by default; ages are minutes relative to NOW."""
    global _id_seq
    _id_seq += 1
    created = NOW - timedelta(minutes=age_minutes)
    return RowView(
        id=_id_seq,
        type_key=type_key,
        kind=kind,
        priority=priority,
        counts_toward_cap=counts_toward_cap,
        created_at=created,
        not_before=NOW + timedelta(minutes=not_before_minutes),
        next_attempt_at=NOW + timedelta(minutes=not_before_minutes),
        expires_at=NOW + timedelta(minutes=expires_minutes),
        payload=payload or {},
    )


def _history(
    cap_used: int = 0,
    singles: dict[str, int] | None = None,
    last_batch: dict[str, datetime] | None = None,
) -> SentHistory:
    return SentHistory(
        cap_used=cap_used,
        singles_in_window=singles or {},
        last_batch_at=last_batch or {},
    )


class TestReadyFilter:
    def test_expired_and_not_ready_ignored(self, bot_config):
        expired = _row(expires_minutes=-1)
        future = _row(not_before_minutes=+5)
        ready = _row()
        result = compose([expired, future, ready], _history(), bot_config, NOW)
        assert [m.row_ids for m in result.messages] == [(ready.id,)]
        assert result.deferred == {}


class TestDailyCap:
    def test_over_cap_collapses_to_summary(self, bot_config):
        """T4: m > Cd -> exactly Cd messages, the last one SUMMARY."""
        cap = bot_config.limits.daily_cap_normal  # 8
        rows = [
            _row(age_minutes=100 - i) for i in range(cap + 4)
        ]
        result = compose(rows, _history(), bot_config, NOW)

        assert len(result.messages) == cap
        singles = result.messages[:-1]
        summary = result.messages[-1]
        assert all(m.render_mode == "SINGLE" for m in singles)
        assert summary.render_mode == "SUMMARY"
        assert summary.type_key is None
        assert summary.counts_toward_cap is True
        # 7 singles + the remaining 5 rows inside the summary.
        assert len(summary.row_ids) == 5
        assert summary.collapsed_counts == (("TICK_DIGEST", 5),)

    def test_cap_used_shrinks_free_slots(self, bot_config):
        """T4 with U > 0: free slots = Cd - U."""
        cap = bot_config.limits.daily_cap_normal
        rows = [_row(age_minutes=50 - i) for i in range(cap + 4)]
        result = compose(rows, _history(cap_used=3), bot_config, NOW)

        assert len(result.messages) == cap - 3
        summary = result.messages[-1]
        assert summary.render_mode == "SUMMARY"
        # cap-3-1 singles pass, the rest collapse.
        assert len(summary.row_ids) == (cap + 4) - (cap - 3 - 1)

    def test_zero_free_slots_sends_nothing(self, bot_config):
        rows = [_row() for _ in range(3)]
        result = compose(
            rows,
            _history(cap_used=bot_config.limits.daily_cap_normal),
            bot_config,
            NOW,
        )
        assert result.messages == []
        assert result.deferred == {}


class TestMerge:
    def test_over_cap_singles_plus_batch(self, bot_config):
        """T5: 5 dispatches -> 3 singles (max_per_window) + 1 batch of 2."""
        rows = [
            _row("DIPLOMATIC_DISPATCH", age_minutes=10 - i)
            for i in range(5)
        ]
        result = compose(rows, _history(), bot_config, NOW)

        assert [m.render_mode for m in result.messages] == [
            "SINGLE",
            "SINGLE",
            "SINGLE",
            "BATCH",
        ]
        batch = result.messages[-1]
        assert len(batch.row_ids) == 2
        assert batch.type_key == "DIPLOMATIC_DISPATCH"
        assert result.deferred == {}

    def test_over_cap_recent_batch_defers_remainder(self, bot_config):
        """T5b: a BATCH of the type inside its window pushes the
        remainder to last_batch_at + window_minutes."""
        rows = [
            _row("DIPLOMATIC_DISPATCH", age_minutes=10 - i)
            for i in range(5)
        ]
        last_batch = NOW - timedelta(minutes=30)  # window is 60
        result = compose(
            rows,
            _history(last_batch={"DIPLOMATIC_DISPATCH": last_batch}),
            bot_config,
            NOW,
        )

        assert [m.render_mode for m in result.messages] == [
            "SINGLE"
        ] * 3
        resume = last_batch + timedelta(minutes=60)
        assert result.deferred == {rows[3].id: resume, rows[4].id: resume}

    def test_singles_in_window_shrink_free_slots(self, bot_config):
        rows = [
            _row("DIPLOMATIC_DISPATCH", age_minutes=10 - i)
            for i in range(4)
        ]
        result = compose(
            rows,
            _history(singles={"DIPLOMATIC_DISPATCH": 2}),
            bot_config,
            NOW,
        )
        # max_per_window 3 - 2 already sent -> 1 single + batch of 3.
        assert [m.render_mode for m in result.messages] == [
            "SINGLE",
            "BATCH",
        ]
        assert len(result.messages[1].row_ids) == 3

    def test_always_merge(self, bot_config):
        """DIRECTIVE_STATUS merge=always: 1 row -> SINGLE, 3 -> BATCH."""
        one = compose(
            [_row("DIRECTIVE_STATUS")], _history(), bot_config, NOW
        )
        assert [m.render_mode for m in one.messages] == ["SINGLE"]

        three = compose(
            [_row("DIRECTIVE_STATUS", age_minutes=9 - i) for i in range(3)],
            _history(),
            bot_config,
            NOW,
        )
        assert [m.render_mode for m in three.messages] == ["BATCH"]
        assert len(three.messages[0].row_ids) == 3


class TestHeadOfQueue:
    def test_critical_and_reply_first_out_of_cap(self, bot_config):
        """T12: critical and REPLY singles lead the batch and never
        count toward the cap."""
        digest = _row(age_minutes=50)
        alert = _row(
            "RED_ALERT",
            priority="critical",
            counts_toward_cap=False,
            age_minutes=5,
        )
        reply = _row(
            "DIALOG",
            kind="REPLY",
            counts_toward_cap=False,
            age_minutes=7,
        )
        result = compose(
            [digest, reply, alert], _history(), bot_config, NOW
        )

        assert [m.row_ids[0] for m in result.messages] == [
            alert.id,
            reply.id,
            digest.id,
        ]
        assert [m.render_mode for m in result.messages] == ["SINGLE"] * 3
        head = result.messages[:2]
        assert all(not m.counts_toward_cap for m in head)
