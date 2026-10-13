"""
Callback endpoint tests — Spec 5.1, Appendix T: T13.

Real DB; VK is not on this path at all (the endpoint never calls it).
Covers the Spec 5.1 order: 404 when off, 413 over 64 KiB, 400 on bad
JSON, 403 on group_id/secret, confirmation verbatim, the journal's
idempotency, consent signals and the never-answer-``remove`` contract
(INV-B12: no secret, body or message text in logs).
"""

from __future__ import annotations

import json
import logging

import pytest
from sqlalchemy import func, select

from modules._00_core.models import Player
from modules._02_bot.models import BotConsent, BotOutbox, BotVkEvent
from tests.modules._02_bot._issue3_support import add_outbox
from tests.modules._02_bot._issue4_support import (
    CALLBACK_SECRET,
    CONFIRMATION,
    vk_body,
)

pytest_plugins = ["tests.modules._02_bot._issue4_fixtures"]


async def _journal(session, event_id: str | None = None):
    query = select(BotVkEvent)
    if event_id is not None:
        query = query.where(BotVkEvent.event_id == event_id)
    return (await session.execute(query)).scalars().all()


async def _consent(session, vk_user_id: int) -> BotConsent | None:
    return (
        await session.execute(
            select(BotConsent)
            .join(Player, Player.id == BotConsent.player_id)
            .where(Player.vk_user_id == vk_user_id)
        )
    ).scalar_one_or_none()


class TestAvailability:
    """Mode gating and request validation, in the Spec 5.1 order."""

    async def test_bot_off_404(self, client, bot_off_env):
        resp = await client.post("/api/v1/bot/callback", json=vk_body("message_allow"))
        assert resp.status_code == 404

    async def test_oversized_body_413(self, client, bot_started):
        resp = await client.post(
            "/api/v1/bot/callback",
            content=b'{"type": "' + b"x" * (70 * 1024) + b'"}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413

    @pytest.mark.parametrize(
        "content",
        [
            b"not json at all",
            b'["a", "list"]',
            b'{"type": 5}',
            b'{"object": {}}',
        ],
        ids=["not-json", "not-object", "type-not-str", "no-type"],
    )
    async def test_bad_body_400(self, client, bot_started, content):
        resp = await client.post(
            "/api/v1/bot/callback",
            content=content,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "overrides",
        [
            {"group_id": 99999},
            {"group_id": "99999"},
            {"secret": "wrong-secret"},
            {"secret": None},
        ],
        ids=["group-id-int", "group-id-str", "wrong-secret", "no-secret"],
    )
    async def test_forbidden_403_empty_body(
        self, client, bot_started, overrides
    ):
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body("message_allow", event_id="e-403", obj={"user_id": 1}, **overrides),
        )
        assert resp.status_code == 403
        assert resp.content == b""


class TestProcessing:
    """Journal, idempotency and the consent/dispatch contract."""

    async def test_confirmation_verbatim_no_journal(
        self, client, bot_started, test_db_session
    ):
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body("confirmation", event_id="e-conf"),
        )
        assert resp.status_code == 200
        assert resp.text == CONFIRMATION
        assert resp.headers["content-type"].startswith("text/plain")
        assert await _journal(test_db_session) == []

    async def test_message_allow_creates_player_and_consent(
        self, client, bot_started, test_db_session
    ):
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body(
                "message_allow", event_id="e-allow", obj={"user_id": 4242}
            ),
        )
        assert resp.status_code == 200
        assert resp.text == "ok"
        player = (
            await test_db_session.execute(
                select(Player).where(Player.vk_user_id == 4242)
            )
        ).scalar_one()
        consent = await _consent(test_db_session, 4242)
        assert consent.state == "ALLOWED"
        assert consent.player_id == player.id
        (journal,) = await _journal(test_db_session, "e-allow")
        assert journal.event_type == "message_allow"
        assert journal.vk_user_id == 4242

    async def test_message_allow_lifts_denied(
        self, client, bot_started, test_db_session
    ):
        await client.post(
            "/api/v1/bot/callback",
            json=vk_body("message_deny", event_id="e-d1", obj={"user_id": 4242}),
        )
        await client.post(
            "/api/v1/bot/callback",
            json=vk_body("message_allow", event_id="e-a1", obj={"user_id": 4242}),
        )
        consent = await _consent(test_db_session, 4242)
        assert consent.state == "ALLOWED"
        assert consent.state_source == "VK_EVENT"

    async def test_message_deny_drops_pending_notifications(
        self, client, bot_started, test_db_session
    ):
        await client.post(
            "/api/v1/bot/callback",
            json=vk_body("message_allow", event_id="e-a2", obj={"user_id": 555}),
        )
        player = (
            await test_db_session.execute(
                select(Player).where(Player.vk_user_id == 555)
            )
        ).scalar_one()
        pending = await add_outbox(
            test_db_session, player.id, type_key="TICK_DIGEST"
        )
        await test_db_session.commit()

        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body("message_deny", event_id="e-d2", obj={"user_id": 555}),
        )
        assert resp.status_code == 200
        consent = await _consent(test_db_session, 555)
        assert consent.state == "DENIED"
        await test_db_session.refresh(pending)
        assert pending.status == "DROPPED"
        assert pending.drop_reason == "NO_CONSENT"

    async def test_duplicate_event_id_handled_once(
        self, client, bot_started, test_db_session
    ):
        body = vk_body("message_allow", event_id="e-dup", obj={"user_id": 777})
        first = await client.post("/api/v1/bot/callback", json=body)
        second = await client.post("/api/v1/bot/callback", json=body)
        assert (first.status_code, first.text) == (200, "ok")
        assert (second.status_code, second.text) == (200, "ok")
        rows = await _journal(test_db_session, "e-dup")
        assert len(rows) == 1
        players = (
            await test_db_session.execute(
                select(func.count())
                .select_from(Player)
                .where(Player.vk_user_id == 777)
            )
        ).scalar_one()
        assert players == 1

    async def test_unknown_type_journaled_ok(
        self, client, bot_started, test_db_session
    ):
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body(
                "message_event", event_id="e-unk", obj={"user_id": 9}
            ),
        )
        assert resp.status_code == 200
        assert resp.text == "ok"
        (row,) = await _journal(test_db_session, "e-unk")
        assert row.event_type == "message_event"
        assert row.vk_user_id == 9

    async def test_malformed_message_new_not_journaled(
        self, client, bot_started, test_db_session
    ):
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body(
                "message_new",
                event_id="e-bad",
                obj={"message": "not-a-dict"},
            ),
        )
        assert resp.status_code == 200
        assert resp.text == "ok"
        assert await _journal(test_db_session, "e-bad") == []
        outbox = (
            await test_db_session.execute(select(BotOutbox))
        ).scalars().all()
        assert outbox == []

    async def test_missing_event_id_skipped(
        self, client, bot_started, test_db_session
    ):
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body("message_allow", obj={"user_id": 31337}),
        )
        assert resp.status_code == 200
        assert resp.text == "ok"
        assert await _journal(test_db_session) == []
        players = (
            await test_db_session.execute(
                select(func.count()).select_from(Player)
            )
        ).scalar_one()
        assert players == 0

    async def test_handler_failure_never_remove(
        self, client, bot_started, test_db_session, monkeypatch
    ):
        async def _boom(*args, **kwargs):
            raise RuntimeError("simulated handler failure")

        monkeypatch.setattr(
            "modules._02_bot.router.handle_event", _boom
        )
        resp = await client.post(
            "/api/v1/bot/callback",
            json=vk_body("message_allow", event_id="e-boom", obj={"user_id": 1}),
        )
        assert resp.status_code == 200
        assert resp.text == "ok"  # never "remove"
        assert await _journal(test_db_session, "e-boom") == []


class TestPrivacy:
    """INV-B12: no secret, request body or message text in logs."""

    async def test_nothing_sensitive_in_logs(
        self, client, bot_started, caplog
    ):
        mark_secret = "WRONG-SECRET-DEADBEEF"
        mark_text = "PLAYER-SECRET-TEXT-XYZ"
        with caplog.at_level(logging.DEBUG):
            await client.post(
                "/api/v1/bot/callback",
                json=vk_body(
                    "message_allow", event_id="e-s1",
                    obj={"user_id": 1}, secret=mark_secret,
                ),
            )
            await client.post(
                "/api/v1/bot/callback",
                json={
                    "type": "message_new",
                    "group_id": 12345,
                    "event_id": "e-s2",
                    "secret": CALLBACK_SECRET,
                    "object": {
                        "message": {
                            "from_id": 11,
                            "peer_id": 11,
                            "out": 0,
                            "text": mark_text,
                        }
                    },
                },
            )
        assert mark_secret not in caplog.text
        assert mark_text not in caplog.text
        assert CALLBACK_SECRET not in caplog.text
