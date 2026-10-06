"""
Dialog handler tests — Spec 3.9, Appendix T: T14.

The handler never calls VK (the dialog path needs no FakeVk at all);
it writes consent rows and ``REPLY`` outbox rows which the sender
delivers. Covers the command surface, the plate cooldown's conditional
UPDATE, the ignore rules, reply-row fields and the end-to-end pass
through the real sender with ``FakeVk`` (INV-B12: message text is
never stored).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from modules._00_core.models import Player
from modules._02_bot.claim import claim_batch
from modules._02_bot.models import BotOutbox, BotVkEvent
from modules._02_bot.settings import read_bot_env
from tests.fixtures.fake_vk import form_keyboard
from tests.modules._02_bot._issue3_support import (
    add_consent,
    add_member,
    add_player,
    make_session_factory,
)
from tests.modules._02_bot._issue4_support import (
    message_new_body,
    vk_body,
)

pytest_plugins = ["tests.modules._02_bot._issue4_fixtures"]

VK_USER = 9001


async def _warm_contact(client, vk_user_id: int = VK_USER) -> None:
    """Journal one earlier message_new so the next event is not the
    first contact (the first contact always gets the greeting)."""
    await client.post(
        "/api/v1/bot/callback",
        json=message_new_body(vk_user_id, f"e-warm-{vk_user_id}", text="x"),
    )


async def _replies(session) -> list[BotOutbox]:
    return (
        (
            await session.execute(
                select(BotOutbox)
                .where(BotOutbox.kind == "REPLY")
                .order_by(BotOutbox.id)
            )
        )
        .scalars()
        .all()
    )


class TestCommands:
    """The Spec 3.9 reply table."""

    async def test_start_command_guest(
        self, client, bot_started, test_db_session
    ):
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-start", payload='{"command": "start"}'
            ),
        )
        (row,) = await _replies(test_db_session)
        assert row.payload["template"] == "start_guest"
        assert row.payload["vars"] == {}
        assert row.payload["keyboard"] == "AUTO"
        assert row.kind == "REPLY"
        assert row.type_key == "DIALOG"
        assert row.priority == "normal"
        assert row.counts_toward_cap is False
        assert row.event_key == "vk:e-start"

    async def test_start_command_member(
        self, client, bot_started, test_db_session
    ):
        member = await add_member(test_db_session, vk_user_id=VK_USER)
        await test_db_session.commit()
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-start-m", payload='{"command": "start"}'
            ),
        )
        (row,) = await _replies(test_db_session)
        assert row.payload["template"] == "start_member"
        assert row.payload["vars"]["nation_name"].startswith("N-")
        assert row.player_id == member.id

    async def test_first_contact_free_text_greets(
        self, client, bot_started, test_db_session
    ):
        """A first message, whatever its text, gets the greeting."""
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-first", text="привет"),
        )
        (row,) = await _replies(test_db_session)
        assert row.payload["template"] == "start_guest"

    async def test_status_member_has_seven_variables(
        self, client, bot_started, test_db_session
    ):
        await add_member(test_db_session, vk_user_id=VK_USER)
        await test_db_session.commit()
        # e-status-0 makes e-status a non-first contact.
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-status-0", text="x"),
        )
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-status", payload='{"cmd": "status"}'
            ),
        )
        (row,) = [
            r for r in await _replies(test_db_session)
            if r.event_key == "vk:e-status"
        ]
        assert row.payload["template"] == "status"
        assert set(row.payload["vars"]) == {
            "nation_name",
            "leader_title",
            "leader_name",
            "province_count",
            "turn",
            "game_date",
            "next_tick_time",
        }

    async def test_status_guest_gets_greeting(
        self, client, bot_started, test_db_session
    ):
        """A guest's ``status`` command gets ``start_guest`` (Spec 3.9)."""
        player = await add_player(test_db_session, vk_user_id=VK_USER)
        await add_consent(test_db_session, player.id)
        await test_db_session.commit()
        # An earlier message_new so this one is not the first contact.
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-g0", text="x"),
        )
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-g1", payload='{"cmd": "status"}'
            ),
        )
        rows = await _replies(test_db_session)
        assert [r.payload["template"] for r in rows] == [
            "start_guest",
            "start_guest",
        ]

    async def test_help_command_help_keyboard(
        self, client, bot_started, test_db_session
    ):
        await _warm_contact(client)
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-help", payload='{"cmd": "help"}'
            ),
        )
        rows = await _replies(test_db_session)
        row = rows[-1]
        assert row.payload["template"] == "help"
        assert row.payload["keyboard"] == "HELP"

    async def test_label_text_acts_as_command(
        self, client, bot_started, test_db_session
    ):
        """Label matching is case- and whitespace-insensitive."""
        await add_member(test_db_session, vk_user_id=VK_USER)
        await test_db_session.commit()
        # e-lbl-0 makes e-lbl a non-first contact.
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-lbl-0", text="x"),
        )
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-lbl", text="  сТаТуС  "),
        )
        rows = await _replies(test_db_session)
        assert rows[-1].payload["template"] == "status"


class TestPlateAndIgnore:
    """Free text, the cooldown gate and the Spec 3.9 ignore rules."""

    async def test_free_text_plate_once_per_cooldown(
        self, client, bot_started, test_db_session
    ):
        """Two sequential free-text events yield exactly one plate."""
        # First contact — greeting, not a plate.
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-c1", text="прочее"),
        )
        # Second and third free text — one plate for the first of them.
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-c2", text="ещё текст"),
        )
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-c3", text="и ещё"),
        )
        rows = await _replies(test_db_session)
        templates = [r.payload["template"] for r in rows]
        assert templates == ["start_guest", "plate"]

    async def test_unknown_payload_is_free_text(
        self, client, bot_started, test_db_session
    ):
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-p0", text="x"),
        )  # first contact -> greeting
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-p1", payload='{"cmd": "forged"}'
            ),
        )
        rows = await _replies(test_db_session)
        assert rows[-1].payload["template"] == "plate"

    @pytest.mark.parametrize(
        "message",
        [
            {"from_id": 0, "peer_id": 0, "out": 0, "text": "hi"},
            {"from_id": VK_USER, "peer_id": VK_USER, "out": 1, "text": "hi"},
            {"from_id": VK_USER, "peer_id": 2000000001, "out": 0, "text": "hi"},
        ],
        ids=["from-id-zero", "out-1", "peer-not-from"],
    )
    async def test_ignored_messages_journal_only(
        self, client, bot_started, test_db_session, message
    ):
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body(
                "message_new",
                event_id="e-ign",
                obj={"message": message},
            ),
        )
        assert resp.status_code == 200
        assert await _replies(test_db_session) == []
        (journal,) = (
            await test_db_session.execute(
                select(BotVkEvent).where(BotVkEvent.event_id == "e-ign")
            )
        ).scalars().all()
        assert journal.event_type == "message_new"

    async def test_reply_needs_no_consent(
        self, client, bot_started, test_db_session
    ):
        """A DENIED player still gets a reply row (V7)."""
        player = await add_player(test_db_session, vk_user_id=VK_USER)
        await add_consent(test_db_session, player.id, state="DENIED")
        await test_db_session.commit()
        await _warm_contact(client)
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-denied", payload='{"cmd": "help"}'
            ),
        )
        rows = await _replies(test_db_session)
        row = rows[-1]
        assert row.payload["template"] == "help"
        assert row.player_id == player.id

    async def test_reply_row_fields(
        self, client, bot_started, test_db_session
    ):
        """expires_at = now + dialog.reply_ttl_minutes; event_key prefix."""
        await _warm_contact(client)
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-fields", payload='{"cmd": "help"}'
            ),
        )
        rows = await _replies(test_db_session)
        row = rows[-1]
        ttl = row.expires_at - row.created_at
        assert ttl == timedelta(minutes=10)
        assert row.status == "PENDING"
        assert row.attempts == 0

    async def test_message_text_never_stored(
        self, client, bot_started, test_db_session
    ):
        mark = "UNIQUE-PLAYER-TEXT-MARK"
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-txt", text=mark),
        )
        outbox = (
            await test_db_session.execute(select(BotOutbox))
        ).scalars().all()
        events = (
            await test_db_session.execute(select(BotVkEvent))
        ).scalars().all()
        blob = json.dumps(
            [r.payload for r in outbox], ensure_ascii=False
        ) + json.dumps(
            [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "vk_user_id": e.vk_user_id,
                }
                for e in events
            ],
            ensure_ascii=False,
        )
        assert mark not in blob


class TestEndToEnd:
    """Callback -> outbox -> real sender -> FakeVk (Spec 3.3/5.5)."""

    async def _deliver(self, engine, runtime):
        now = datetime.now(timezone.utc)
        async with make_session_factory(engine)() as session:
            groups = await claim_batch(
                session,
                runtime._config,
                read_bot_env(),
                now,
            )
            await session.commit()
        await runtime._sender.process_groups(groups)

    async def test_guest_reply_gets_guest_keyboard(
        self, client, bot_started, test_db_engine, fake_vk_runtime
    ):
        fake, runtime = fake_vk_runtime
        fake.respond_send_ok()
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-e2e-g", text="добрый день"),
        )
        await self._deliver(test_db_engine, runtime)
        (send,) = fake.send_requests()
        keyboard = form_keyboard(send)
        buttons = keyboard["buttons"][0]
        labels = [b["action"]["label"] for b in buttons]
        assert "Создать государство" in labels
        assert labels[-1] == "Помощь"
        # open_app deep-link carries the configured app id
        open_app = buttons[0]["action"]
        assert open_app["type"] == "open_app"
        assert open_app["app_id"] == 777

    async def test_member_reply_gets_member_keyboard(
        self,
        client,
        bot_started,
        test_db_engine,
        test_db_session,
        fake_vk_runtime,
    ):
        fake, runtime = fake_vk_runtime
        await add_member(test_db_session, vk_user_id=VK_USER)
        await test_db_session.commit()
        fake.respond_send_ok()
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(VK_USER, "e-e2e-m", text="ход"),
        )
        await self._deliver(test_db_engine, runtime)
        (send,) = fake.send_requests()
        labels = [
            b["action"]["label"]
            for row in form_keyboard(send)["buttons"]
            for b in row
        ]
        assert labels == ["Статус", "Помощь"]

    async def test_help_reply_gets_inline_links(
        self, client, bot_started, test_db_engine, fake_vk_runtime
    ):
        fake, runtime = fake_vk_runtime
        fake.respond_send_ok()
        await _warm_contact(client)
        await client.post(
            "/api/v1/bot/callback",
            json=message_new_body(
                VK_USER, "e-e2e-h", payload='{"cmd": "help"}'
            ),
        )
        await self._deliver(test_db_engine, runtime)
        # Two replies went out (warm-up greeting + help) in unspecified
        # order; the help one is the message with open_link actions.
        keyboards = [form_keyboard(r) for r in fake.send_requests()]
        inline = [
            kb
            for kb in keyboards
            if kb and kb.get("inline") is True
        ]
        (keyboard,) = inline
        actions = [
            b["action"] for row in keyboard["buttons"] for b in row
        ]
        assert all(a["type"] == "open_link" for a in actions)
        assert any(
            "vk.ru/@pax_atom-404" in a.get("link", "") for a in actions
        )
