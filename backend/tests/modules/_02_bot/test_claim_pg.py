"""
Issue 3 checks on real PostgreSQL (Spec 3.2; service.py carry-over).

- Two concurrent claims on different connections receive disjoint
  rows: worker A holds ``FOR UPDATE`` locks on the first players'
  rows; worker B's ``SKIP LOCKED`` select jumps past them and takes
  the rest — without blocking.
- ``BotService.enqueue`` never issues the SQLite transaction-opening
  no-op ``DELETE`` on PostgreSQL (Issue 2 review carry-over).

Requires DATABASE_URL_TEST; the shared pg fixtures wipe/rebuild the
schema and reset data per test.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from modules._02_bot.claim import claim_batch
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.models import BotOutbox
from modules._02_bot.service import BotService
from modules._02_bot.settings import BotEnv
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.modules._02_bot._issue3_support import (
    NOW,
    add_consent,
    add_member,
    add_outbox,
)

pytestmark = pytest.mark.postgres

ENV = BotEnv(
    enabled=True,
    group_id="12345",
    group_token="t",
    callback_secret="s",
    callback_confirmation="c",
    app_id=777,
)

_DIGEST_VARS = {
    "turn": 1,
    "game_date": "2026-01-08",
    "nation_name": "N",
    "province_count": 1,
    "next_tick_time": "завтра",
}


class TestConcurrentClaims:
    async def test_skip_locked_disjoint_rows(
        self, pg_db, bot_config
    ):
        """Worker A leases the two oldest players' rows and holds the
        transaction open; worker B (larger batch) skips the locked
        rows and leases only the third player's — disjoint, no wait."""
        async with pg_db() as session:
            oldest = await add_member(session)
            middle = await add_member(session)
            newest = await add_member(session)
            for i, player in enumerate((oldest, middle, newest)):
                await add_outbox(
                    session,
                    player.id,
                    payload=_DIGEST_VARS,
                    created_at=NOW - timedelta(minutes=10 - i),
                )
            await session.commit()

        small = bot_config.model_copy(deep=True)
        small.sender.claim_batch_size = 2

        # Worker A claims the two oldest players and keeps its
        # transaction (and row locks) open.
        session_a = pg_db()
        await session_a.begin()
        try:
            groups_a = await claim_batch(session_a, small, ENV, NOW)
            rows_a = {
                row_id for g in groups_a for row_id in g.row_ids
            }
            assert len(rows_a) == 2

            # Worker B sees all three players but must not wait on A's
            # locks — SKIP LOCKED hands it the remaining row only.
            session_b = pg_db()
            await session_b.begin()
            try:
                groups_b = await asyncio.wait_for(
                    claim_batch(session_b, bot_config, ENV, NOW),
                    timeout=15,
                )
                rows_b = {
                    row_id for g in groups_b for row_id in g.row_ids
                }
                assert len(rows_b) == 1
                assert rows_a.isdisjoint(rows_b)
                # B's row belongs to the newest (unlocked) player.
                assert groups_b[0].player_id == newest.id
                await session_b.commit()
            finally:
                await session_b.close()
            await session_a.commit()
        finally:
            await session_a.close()


class TestNoSqliteWorkaround:
    async def test_enqueue_issues_no_noop_delete(
        self, pg_db, bot_config, bot_started
    ):
        """The DELETE-WHERE-false transaction kick is SQLite-only;
        on PostgreSQL enqueue emits none."""
        statements: list[str] = []
        engine = pg_db.kw["bind"]

        def _capture(
            conn, cursor, statement, parameters, context, executemany
        ):
            statements.append(statement)

        sa.event.listen(
            engine.sync_engine, "before_cursor_execute", _capture
        )
        try:
            async with pg_db() as session:
                player = await add_member(session)
                await session.commit()

            async with pg_db() as session:
                result = await BotService.enqueue(
                    session,
                    type_key="TICK_DIGEST",
                    player_id=player.id,
                    event_key="pg-enqueue-check",
                    variables=_DIGEST_VARS,
                )
                await session.commit()
        finally:
            sa.event.remove(
                engine.sync_engine, "before_cursor_execute", _capture
            )

        assert result.name == "QUEUED"
        assert not any(
            "DELETE FROM bot_outbox" in statement
            for statement in statements
        ), "enqueue issued the SQLite no-op DELETE on PostgreSQL"
