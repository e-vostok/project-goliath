"""
Tests for the claim step (Spec 3.2, Appendix T: T6, T7, T8, T12).

Real DB; claim_batch runs in a session the test commits itself, the
way the sender does. Covers expiry and attempts bookkeeping, player
priority ordering, consent/nation drops, the crash-recovery path that
reuses a stored group_id/random_id (INV-B6) versus dissolving a
broken group, and the sent-history limits of Spec 3.4.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from modules._02_bot.claim import claim_batch
from modules._02_bot.models import BotOutbox
from modules._02_bot.settings import BotEnv
from tests.modules._02_bot._issue3_support import (
    NOW,
    add_member,
    add_outbox,
    aware,
    make_session_factory,
)

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


async def _claim(engine, config, now=NOW):
    async with make_session_factory(engine)() as session:
        groups = await claim_batch(session, config, ENV, now)
        await session.commit()
    return groups


async def _rows(engine, player_id):
    async with make_session_factory(engine)() as session:
        result = await session.execute(
            select(BotOutbox)
            .where(BotOutbox.player_id == player_id)
            .order_by(BotOutbox.id)
        )
        return list(result.scalars().all())


async def _row(engine, row_id) -> BotOutbox:
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(BotOutbox).where(BotOutbox.id == row_id)
            )
        ).scalar_one()


class TestHousekeeping:
    async def test_expired_rows_expire_without_vk(
        self, test_db_engine, bot_config
    ):
        """T6: an expired row flips to EXPIRED inside claim — nothing
        ever reaches a VK call."""
        async with make_session_factory(test_db_engine)() as session:
            player = await add_member(session)
            await add_outbox(
                session,
                player.id,
                payload=_DIGEST_VARS,
                expires_at=NOW - timedelta(minutes=1),
            )
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        assert groups == []
        assert (await _rows(test_db_engine, player.id))[0].status == "EXPIRED"

    async def test_attempts_exhausted_fails(
        self, test_db_engine, bot_config
    ):
        async with make_session_factory(test_db_engine)() as session:
            player = await add_member(session)
            await add_outbox(
                session,
                player.id,
                payload=_DIGEST_VARS,
                attempts=bot_config.sender.max_attempts,
            )
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        assert groups == []
        row = (await _rows(test_db_engine, player.id))[0]
        assert row.status == "FAILED"
        assert row.drop_reason == "ATTEMPTS_EXHAUSTED"


class TestPlayerOrdering:
    async def test_critical_player_first(
        self, test_db_engine, bot_config
    ):
        """T12: a player with a critical row claims before one with an
        older but ordinary row."""
        async with make_session_factory(test_db_engine)() as session:
            patient = await add_member(session)
            urgent = await add_member(session)
            await add_outbox(
                session,
                patient.id,
                payload=_DIGEST_VARS,
                created_at=NOW - timedelta(hours=2),
            )
            await add_outbox(
                session,
                urgent.id,
                type_key="RED_ALERT",
                priority="critical",
                counts_toward_cap=False,
                payload={"event_text": "удар"},
                created_at=NOW - timedelta(minutes=1),
            )
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        assert groups[0].player_id == urgent.id
        assert groups[0].rows[0].priority == "critical"


class TestPlayerChecks:
    async def test_no_consent_and_no_nation_drop(
        self, test_db_engine, bot_config
    ):
        async with make_session_factory(test_db_engine)() as session:
            denied = await add_member(session, consent="DENIED")
            nationless = await add_member(session, consent="ALLOWED")
            # Remove the nation — the consent stays ALLOWED.
            from modules._00_core.models import Nation

            nation = (
                await session.execute(
                    select(Nation).where(
                        Nation.owner_player_id == nationless.id
                    )
                )
            ).scalar_one()
            await session.delete(nation)
            for player in (denied, nationless):
                await add_outbox(session, player.id, payload=_DIGEST_VARS)
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        assert groups == []
        assert (await _rows(test_db_engine, denied.id))[0].drop_reason == (
            "NO_CONSENT"
        )
        assert (await _rows(test_db_engine, nationless.id))[
            0
        ].drop_reason == "NO_NATION"

    async def test_reply_needs_neither(
        self, test_db_engine, bot_config
    ):
        """A REPLY row claims even for a guest with no consent."""
        async with make_session_factory(test_db_engine)() as session:
            guest = await add_member(session, consent=None)
            from modules._00_core.models import Nation

            nation = (
                await session.execute(
                    select(Nation).where(
                        Nation.owner_player_id == guest.id
                    )
                )
            ).scalar_one()
            await session.delete(nation)
            await add_outbox(
                session,
                guest.id,
                kind="REPLY",
                type_key="DIALOG",
                counts_toward_cap=False,
                payload={
                    "template": "help",
                    "vars": {},
                    "keyboard": "AUTO",
                },
            )
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        assert len(groups) == 1
        assert groups[0].rows[0].kind == "REPLY"


class TestGroupReassembly:
    async def test_expired_lease_reclaims_same_group(
        self, test_db_engine, bot_config
    ):
        """T8: a crashed worker's leased rows reclaim into the SAME
        group with the SAME random_id."""
        async with make_session_factory(test_db_engine)() as session:
            player = await add_member(session)
            group_id = str(uuid.uuid4())
            expired_lease = NOW - timedelta(minutes=5)
            for i in range(2):
                await add_outbox(
                    session,
                    player.id,
                    type_key="DIRECTIVE_STATUS",
                    payload={
                        "directive_title": f"Д-{i}",
                        "status_text": "готово",
                    },
                    status="LEASED",
                    attempts=1,
                    lease_until=expired_lease,
                    lease_token="old-token",
                    group_id=group_id,
                    random_id=424242,
                    render_mode="BATCH",
                )
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        assert len(groups) == 1
        group = groups[0]
        assert group.group_id == group_id
        assert group.random_id == 424242
        assert group.render_mode == "BATCH"
        rows = await _rows(test_db_engine, player.id)
        assert {r.attempts for r in rows} == {2}
        assert {r.status for r in rows} == {"LEASED"}
        assert aware(rows[0].lease_until) == NOW + timedelta(
            seconds=bot_config.sender.lease_seconds
        )

    async def test_broken_group_dissolves(
        self, test_db_engine, bot_config
    ):
        """A group missing a row dissolves: the survivor gets a fresh
        group_id and random_id."""
        async with make_session_factory(test_db_engine)() as session:
            player = await add_member(session)
            group_id = str(uuid.uuid4())
            expired_lease = NOW - timedelta(minutes=5)
            gone = await add_outbox(
                session,
                player.id,
                payload=_DIGEST_VARS,
                status="DROPPED",
                drop_reason="NO_CONSENT",
                group_id=group_id,
                random_id=111,
                render_mode="SINGLE",
            )
            survivor = await add_outbox(
                session,
                player.id,
                payload=_DIGEST_VARS,
                status="LEASED",
                attempts=1,
                lease_until=expired_lease,
                lease_token="old-token",
                group_id=group_id,
                random_id=111,
                render_mode="SINGLE",
            )
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        assert len(groups) == 1
        group = groups[0]
        assert group.group_id != group_id
        assert group.random_id != 111
        assert (await _row(test_db_engine, survivor.id)).group_id == (
            group.group_id
        )


class TestSentHistory:
    async def test_history_feeds_cap_and_windows(
        self, test_db_engine, bot_config
    ):
        """Seeded SENT rows drive cap_used, singles_in_window and
        last_batch_at exactly as Spec 3.4 prescribes."""
        cap = bot_config.limits.daily_cap_normal  # 8
        async with make_session_factory(test_db_engine)() as session:
            capped = await add_member(session)
            # 8 distinct sent groups in the sliding 24h -> cap full.
            for i in range(cap):
                await add_outbox(
                    session,
                    capped.id,
                    status="SENT",
                    group_id=str(uuid.uuid4()),
                    render_mode="SINGLE",
                    sent_at=NOW - timedelta(minutes=30),
                )
            await add_outbox(session, capped.id, payload=_DIGEST_VARS)

            batched = await add_member(session)
            # 3 singles of the over_cap type inside its 60-min window.
            for i in range(3):
                await add_outbox(
                    session,
                    batched.id,
                    type_key="DIPLOMATIC_DISPATCH",
                    status="SENT",
                    group_id=str(uuid.uuid4()),
                    render_mode="SINGLE",
                    sent_at=NOW - timedelta(minutes=10),
                )
            for i in range(4):
                await add_outbox(
                    session,
                    batched.id,
                    type_key="DIPLOMATIC_DISPATCH",
                    payload={"from_nation": "X"},
                )

            windowed = await add_member(session)
            # A batch of the same type 30 min ago: remainder defers to
            # last_batch + window (60 min -> NOW+30).
            last_batch = NOW - timedelta(minutes=30)
            await add_outbox(
                session,
                windowed.id,
                type_key="DIPLOMATIC_DISPATCH",
                status="SENT",
                group_id=str(uuid.uuid4()),
                render_mode="BATCH",
                sent_at=last_batch,
            )
            for i in range(5):
                await add_outbox(
                    session,
                    windowed.id,
                    type_key="DIPLOMATIC_DISPATCH",
                    payload={"from_nation": "X"},
                )
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        by_player = {}
        for group in groups:
            by_player.setdefault(group.player_id, []).append(group)

        # cap_used = cap -> no composed messages at all.
        assert capped.id not in by_player
        assert (await _rows(test_db_engine, capped.id))[-1].status == (
            "PENDING"
        )

        # singles_in_window = max_per_window -> every row lands in one
        # BATCH.
        assert len(by_player[batched.id]) == 1
        batch = by_player[batched.id][0]
        assert batch.render_mode == "BATCH"
        assert len(batch.row_ids) == 4

        # last_batch inside the window -> 3 singles pass, 2 rows
        # deferred to last_batch + 60 minutes.
        windowed_groups = by_player[windowed.id]
        assert len(windowed_groups) == 3
        assert all(g.render_mode == "SINGLE" for g in windowed_groups)
        deferred = [
            row
            for row in await _rows(test_db_engine, windowed.id)
            if row.status == "PENDING"
        ]
        assert len(deferred) == 2
        assert {aware(r.next_attempt_at) for r in deferred} == {
            last_batch + timedelta(minutes=60)
        }
