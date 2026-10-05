"""
Tests for 02_bot ORM models (Spec Part 1.1, Issue 1).

Real SQLite in-memory databases only (Anti-Mock Guard): every check
hits a real constraint — unique, check, FK cascade. The cascade test
builds its own engine with ``PRAGMA foreign_keys=ON`` because the
shared ``test_db_session`` fixture leaves the SQLite default (off);
same trick as tests/modules/_01_map/test_ownership_log.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.db import Base
from modules._00_core.models import Player
from modules._02_bot.models import (
    BotConsent,
    BotOutbox,
    BotState,
    BotVkEvent,
)
from tests.fixtures.factories import (
    make_consent,
    make_outbox_row,
    utcnow,
)


async def _make_player(
    session: AsyncSession, vk_user_id: int = 777000001
) -> Player:
    """Insert a real players row — the only FK target bot tables need."""
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=vk_user_id,
        created_at=utcnow(),
    )
    session.add(player)
    await session.flush()
    return player


class TestRoundTrip:
    """Insert-then-read of each table on the ORM path."""

    async def test_consent_round_trip(self, test_db_session):
        player = await _make_player(test_db_session)
        consent = await make_consent(test_db_session, player)

        row = (
            await test_db_session.execute(
                select(BotConsent).where(BotConsent.player_id == player.id)
            )
        ).scalar_one()
        assert row.player_id == player.id
        assert row.state == "ALLOWED"
        assert row.state_source == "INIT"
        assert row.last_checked_at is None

    async def test_outbox_round_trip(self, test_db_session):
        player = await _make_player(test_db_session)
        queued = await make_outbox_row(
            test_db_session, player, payload={"turn": 1}
        )

        row = (
            await test_db_session.execute(
                select(BotOutbox).where(BotOutbox.id == queued.id)
            )
        ).scalar_one()
        assert row.player_id == player.id
        assert row.type_key == "TICK_DIGEST"
        assert row.status == "PENDING"
        assert row.priority == "normal"
        assert row.kind == "NOTIFICATION"
        assert row.attempts == 0
        assert row.payload == {"turn": 1}
        assert row.expires_at > row.created_at
        # BIGINT-with-INTEGER-variant PK: autoincrement assigned by the
        # database, positive int.
        assert isinstance(row.id, int) and row.id > 0

    async def test_vk_event_round_trip(self, test_db_session):
        event = BotVkEvent(
            event_id="evt-0001",
            event_type="message_allow",
            vk_user_id=777000001,
            received_at=utcnow(),
        )
        test_db_session.add(event)
        await test_db_session.flush()

        row = (
            await test_db_session.execute(
                select(BotVkEvent).where(BotVkEvent.id == event.id)
            )
        ).scalar_one()
        assert row.event_id == "evt-0001"
        assert isinstance(row.id, int) and row.id > 0

    async def test_bot_state_round_trip(self, test_db_session):
        test_db_session.add(BotState(id=1, last_digest_turn=0))
        await test_db_session.flush()

        row = (
            await test_db_session.execute(
                select(BotState).where(BotState.id == 1)
            )
        ).scalar_one()
        assert row.last_digest_turn == 0


class TestConstraints:
    """Every named CHECK/UNIQUE from Spec 1.1 rejects a bad value."""

    async def test_consent_invalid_state_rejected(self, test_db_session):
        player = await _make_player(test_db_session)
        consent = BotConsent(
            player_id=player.id,
            state="BOGUS",
            state_source="INIT",
            state_changed_at=utcnow(),
            created_at=utcnow(),
        )
        test_db_session.add(consent)
        with pytest.raises(IntegrityError):
            await test_db_session.flush()

    @pytest.mark.parametrize(
        "field,bad_value",
        [
            ("kind", "ANNOUNCEMENT"),
            ("priority", "high"),
            ("status", "QUEUED"),
        ],
    )
    async def test_outbox_invalid_values_rejected(
        self, test_db_session, field, bad_value
    ):
        player = await _make_player(test_db_session)
        row = await make_outbox_row(test_db_session, player)
        setattr(row, field, bad_value)
        with pytest.raises(IntegrityError):
            await test_db_session.flush()

    async def test_outbox_dedup_unique_rejected(self, test_db_session):
        """uq_bot_outbox_dedup: one event = one queue row (INV-B5)."""
        player = await _make_player(test_db_session)
        await make_outbox_row(test_db_session, player, event_key="turn:1")
        with pytest.raises(IntegrityError):
            await make_outbox_row(
                test_db_session, player, event_key="turn:1"
            )

    async def test_bot_state_singleton_rejects_second_row(
        self, test_db_session
    ):
        test_db_session.add(BotState(id=1, last_digest_turn=0))
        await test_db_session.flush()
        test_db_session.add(BotState(id=2, last_digest_turn=5))
        with pytest.raises(IntegrityError):
            await test_db_session.flush()

    async def test_vk_event_id_unique(self, test_db_session):
        test_db_session.add(
            BotVkEvent(
                event_id="evt-dup",
                event_type="message_new",
                vk_user_id=None,
                received_at=utcnow(),
            )
        )
        await test_db_session.flush()
        test_db_session.add(
            BotVkEvent(
                event_id="evt-dup",
                event_type="message_new",
                vk_user_id=None,
                received_at=utcnow(),
            )
        )
        with pytest.raises(IntegrityError):
            await test_db_session.flush()


async def _fk_enforcing_session():
    """Engine + sessionmaker with SQLite FK enforcement enabled."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, maker


class TestPlayerCascade:
    """Deleting a player must cascade to bot_consents and bot_outbox
    (ON DELETE CASCADE, Spec 1.1)."""

    async def test_player_delete_cascades(self):
        engine, maker = await _fk_enforcing_session()
        try:
            async with maker() as session:
                player = await _make_player(session)
                await make_consent(session, player)
                await make_outbox_row(session, player)
                await session.commit()

                await session.delete(player)
                await session.commit()

                assert (
                    await session.execute(
                        select(sa.func.count()).select_from(BotConsent)
                    )
                ).scalar_one() == 0
                assert (
                    await session.execute(
                        select(sa.func.count()).select_from(BotOutbox)
                    )
                ).scalar_one() == 0
        finally:
            await engine.dispose()
