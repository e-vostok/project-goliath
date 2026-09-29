"""
Tests for the daily fixed-local-time tick schedule (tick_schedule.py).

Covers next_tick_after() math — same-day rollover, strict "after"
semantics at exactly tick_time, and the October DST fallback where the
UTC instant must move while the local wall-clock time stays fixed — plus
the DB-level wiring: finalize_tick and the admin reset hook must write
next_tick_at from the same function, and the admin state view must expose
tick_timezone and next_tick_at_local.

Anti-Mock Guard: DB tests run on the shared test_db_session fixture
(real in-memory SQLite), no mocked state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from modules._00_core.admin_hooks import admin_reset, admin_state_view
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import GameClock
from modules._00_core.tick_handler import finalize_tick
from modules._00_core.tick_schedule import next_tick_after
from tests.fixtures.factories import GameClockFactory

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
TICK_TZ = ZoneInfo(CORE_CONFIG.tick.tick_timezone)


def _utc(dt: datetime) -> datetime:
    """Normalize a possibly-naive DB datetime to aware UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _expected_candidates(before: datetime, after: datetime) -> set[datetime]:
    """
    The set of values next_tick_after() may legitimately have produced
    for a call whose `now` falls anywhere inside [before, after] —
    two entries only when the window straddles a local tick boundary.
    """
    return {
        next_tick_after(
            t, CORE_CONFIG.tick.tick_time, CORE_CONFIG.tick.tick_timezone
        )
        for t in (before, after)
    }


def _assert_local_midnight(utc_dt: datetime) -> None:
    local = utc_dt.astimezone(TICK_TZ)
    assert (local.hour, local.minute, local.second, local.microsecond) == (
        0, 0, 0, 0,
    )


class TestNextTickAfter:
    """Pure-function schedule math on fixed `now` values."""

    def test_midday_returns_coming_midnight_local(self):
        # 12:00 UTC = 15:00 Europe/Moscow -> the same day's midnight MSK.
        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

        result = next_tick_after(now, "00:00", "Europe/Moscow")

        assert result == datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc)

    def test_same_day_future_tick_time(self):
        # 12:00 UTC = 15:00 MSK -> a 16:30 MSK tick is still today.
        now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

        result = next_tick_after(now, "16:30", "Europe/Moscow")

        assert result == datetime(2026, 9, 30, 13, 30, tzinfo=timezone.utc)

    def test_exactly_tick_time_rolls_to_next_day(self):
        # now is exactly 2026-10-01 00:00 Europe/Moscow: strictly-after
        # semantics push the next tick to 2026-10-02 00:00 MSK.
        now = datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc)

        result = next_tick_after(now, "00:00", "Europe/Moscow")

        assert result == datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)

    def test_dst_fallback_shifts_utc_not_local(self):
        """
        Europe/Warsaw falls back 2026-10-25 03:00 CEST -> 02:00 CET, so
        Oct 25 has 25 local hours. A naive "+24h" from Oct 25 00:30 CEST
        would land at 22:30 UTC (00:30 local Oct 26); per-date scheduling
        must land on local midnight: Oct 26 00:00 CET = 23:00 UTC.
        """
        now = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc)

        result = next_tick_after(now, "00:00", "Europe/Warsaw")

        assert result == datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)
        local = result.astimezone(ZoneInfo("Europe/Warsaw"))
        assert (local.hour, local.minute) == (0, 0)

    def test_naive_now_raises_value_error(self):
        with pytest.raises(ValueError):
            next_tick_after(
                datetime(2026, 9, 30, 12, 0), "00:00", "Europe/Moscow"
            )

    def test_invalid_tick_time_raises_value_error(self):
        with pytest.raises(ValueError):
            next_tick_after(
                datetime.now(timezone.utc), "24:00", "Europe/Moscow"
            )


class TestFixedTimeScheduleOnDatabase:
    """DB wiring: finalize_tick, admin reset, and the state view."""

    @pytest.mark.asyncio
    async def test_finalize_tick_sets_next_fixed_local_time(
        self, test_db_session
    ):
        clock = GameClockFactory.build(current_turn=4)
        test_db_session.add(clock)
        await test_db_session.flush()

        before = datetime.now(timezone.utc)
        await finalize_tick(test_db_session, 5)
        after = datetime.now(timezone.utc)

        assert clock.current_turn == 5
        assert clock.last_tick_at is not None
        next_tick_at = _utc(clock.next_tick_at)
        assert next_tick_at in _expected_candidates(before, after)
        _assert_local_midnight(next_tick_at)
        # A manual/out-of-band tick realigns to the daily schedule
        # instead of pushing it out by an interval.
        assert next_tick_at > before

    @pytest.mark.asyncio
    async def test_admin_reset_realigns_to_fixed_local_time(
        self, test_db_session
    ):
        test_db_session.add(
            GameClockFactory.build(
                current_turn=9,
                last_tick_at=datetime.now(timezone.utc),
                next_tick_at=datetime.now(timezone.utc),
            )
        )
        await test_db_session.flush()

        before = datetime.now(timezone.utc)
        await admin_reset(test_db_session)
        after = datetime.now(timezone.utc)

        result = await test_db_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        clock = result.scalar_one()
        assert clock.current_turn == 0
        next_tick_at = _utc(clock.next_tick_at)
        assert next_tick_at in _expected_candidates(before, after)
        _assert_local_midnight(next_tick_at)

    @pytest.mark.asyncio
    async def test_state_view_reports_localized_clock(self, test_db_session):
        # 2026-10-01 21:00 UTC == 2026-10-02 00:00 Europe/Moscow.
        next_tick = datetime(2026, 10, 1, 21, 0, tzinfo=timezone.utc)
        test_db_session.add(GameClockFactory.build(next_tick_at=next_tick))
        await test_db_session.flush()

        view = await admin_state_view(test_db_session)

        clock = view["clock"]
        assert clock["tick_timezone"] == CORE_CONFIG.tick.tick_timezone
        local_dt = datetime.fromisoformat(clock["next_tick_at_local"])
        assert local_dt == next_tick.astimezone(TICK_TZ)
        assert (local_dt.hour, local_dt.minute) == (0, 0)
        assert datetime.fromisoformat(clock["next_tick_at"]) == next_tick
