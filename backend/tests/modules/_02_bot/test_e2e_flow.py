"""
End-to-end flows of module 02_bot (Issue 6, Spec Appendix T).

Each scenario drives the real stack — ASGI client, Callback endpoint,
consent gate, tick orchestrator, watcher/claim/sender steps — with the
ONLY fake being VK HTTP (``FakeVk`` on ``httpx.MockTransport``). No
sleeps: time is injected into the steps that accept ``now``.

E1–E7/E9 run on the in-memory SQLite engine through the ``client``
fixture; E2 uses a file-backed engine so two concurrent watcher passes
run on genuinely separate connections; E8 goes through the real admin
reset endpoint. The ``postgres``-marked class mirrors E1/E2 on a real
database when ``DATABASE_URL_TEST`` is provided (CI).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from core.admin.registry import AdminRegistry
from core.db import Base
from core.tick.orchestrator import TickOrchestrator, TickOutcome
from core.tick.scheduler import run_scheduled_tick
from modules._00_core.admin_hooks import register_admin_hooks
from modules._00_core.calendar import compute_game_date
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import GameClock, Nation, Province
from modules._00_core.tick_handler import finalize_tick
from modules._00_core.tick_schedule import format_game_time
from modules._01_map.hooks import reset_ownership_log
from modules._02_bot.admin_hooks import register_bot_admin_hooks
from modules._02_bot.claim import claim_batch
from modules._02_bot.models import (
    BotConsent,
    BotOutbox,
    BotState,
    BotVkEvent,
)
from modules._02_bot.render import render, sanitize_value
from modules._02_bot.runtime import BotRuntime, install_runtime
from modules._02_bot.settings import get_active_runtime, read_bot_env
from modules._02_bot.startup import startup_bot
from modules._02_bot.watcher import digest_watcher_step
from tests.fixtures.fake_vk import FakeVk, form_keyboard
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,  # noqa: F401 — resolved through the fixture chain
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province
from tests.modules._02_bot._issue3_support import (
    add_bot_state,
    add_consent,
    add_member,
    aware,
    make_session_factory,
)
from tests.modules._02_bot._issue4_support import (
    bearer_headers,
    message_new_body,
    seed_player,
    vk_body,
)

pytest_plugins = ["tests.modules._02_bot._issue4_fixtures"]

CALLBACK_URL = "/api/v1/bot/callback"
NATIONS_URL = "/api/v1/nations"
STATUS_URL = "/api/v1/bot/status"
REFRESH_URL = "/api/v1/bot/consent/refresh"
HEALTH_URL = "/api/v1/health"
RESET_URL = "/api/v1/admin/state/reset"

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
TZ_NAME = CORE_CONFIG.tick.tick_timezone


@pytest.fixture(autouse=True)
def _orchestrator():
    """The real finalize path on an otherwise empty handler set."""
    TickOrchestrator.clear_handlers()
    TickOrchestrator.register_finalize(finalize_tick)
    yield
    TickOrchestrator.clear_handlers()


@pytest.fixture
def bot_started_off(bot_off_env, bot_isolation):
    """startup_bot() over the OFF env — hooks register, gate is inert."""
    return startup_bot()


@pytest_asyncio.fixture
async def file_db_engine(tmp_path):
    """File-backed SQLite: concurrent watcher passes need separate
    connections (the shared :memory: pool serialises them on one)."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/e2e.db",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _nation_body(
    name: str = "Государство Тестовое",
    color: str = "#A1B2C3",
    province_ids: tuple[int, ...] = (1001, 1002),
) -> dict:
    return {
        "name": name,
        "color_hex": color,
        "province_ids": list(province_ids),
        **VALID_PROFILE,
    }


async def _seed_clock(
    session,
    turn: int = 0,
    next_tick_at: datetime | None = None,
) -> None:
    session.add(
        GameClock(
            id=1,
            current_turn=turn,
            last_tick_at=None,
            next_tick_at=next_tick_at
            or datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    await session.flush()


async def _seed_starting_group(
    session, *ids: int
) -> None:
    """Seed LAND provinces; default pair matches ``_nation_body``."""
    for pid in ids or (1001, 1002):
        await make_land_province(session, id=pid)


async def _tick(engine) -> None:
    """One turn through the real scheduler path (admin/manual arm)."""
    async with make_session_factory(engine)() as session:
        outcome = await run_scheduled_tick(session)
    assert outcome is TickOutcome.EXECUTED


async def _watch(engine, config) -> None:
    await digest_watcher_step(make_session_factory(engine), config)


async def _deliver(engine, runtime, now: datetime | None = None):
    """Claim + send exactly as ``_sender_step`` does (no task, no sleep)."""
    t = now or datetime.now(timezone.utc)
    async with make_session_factory(engine)() as session:
        groups = await claim_batch(
            session, runtime._config, runtime._env, t
        )
        await session.commit()
    await runtime._sender.process_groups(groups)
    return groups


async def _outbox_rows(engine) -> list[BotOutbox]:
    async with make_session_factory(engine)() as session:
        return list(
            (await session.execute(select(BotOutbox))).scalars().all()
        )


async def _digest_rows(engine) -> list[BotOutbox]:
    async with make_session_factory(engine)() as session:
        return list(
            (
                await session.execute(
                    select(BotOutbox).where(
                        BotOutbox.type_key == "TICK_DIGEST"
                    )
                )
            ).scalars().all()
        )


async def _consent_of(engine, player_id: str) -> BotConsent | None:
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(BotConsent).where(
                    BotConsent.player_id == player_id
                )
            )
        ).scalar_one_or_none()


async def _digest_turn(engine) -> int | None:
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(BotState.last_digest_turn).where(BotState.id == 1)
            )
        ).scalar_one_or_none()


async def _clock_turn(engine) -> int:
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(GameClock.current_turn).where(GameClock.id == 1)
            )
        ).scalar_one()


def _expected(template: str, variables: dict, config) -> str:
    """The exact outgoing text: render over sanitized vars, as the
    sender does for a SINGLE notification."""
    return render(
        template,
        {
            key: sanitize_value(value, config.limits.variable_max_length)
            for key, value in variables.items()
        },
    )


def _send_form(request) -> dict[str, str]:
    return {
        key: values[0]
        for key, values in parse_qs(request.content.decode()).items()
    }


def _button_labels(keyboard: dict) -> list[str]:
    return [
        button["action"]["label"]
        for row in keyboard["buttons"]
        for button in row
    ]


# ---------------------------------------------------------------------------
# E1 — happy path
# ---------------------------------------------------------------------------


async def test_e1_allow_register_digest_sent(
    client,
    bot_started,
    consent_required,
    test_db_engine,
    test_db_session,
    fake_vk_runtime,
):
    """T1/T13/T21: message_allow -> ALLOWED -> nation -> tick -> one
    rendered TICK_DIGEST to the player's VK id, MEMBER keyboard."""
    fake, runtime = fake_vk_runtime
    config = bot_started
    vk_user = 660101
    fake.respond_send_ok(message_id=4242, peer_id=vk_user)

    player = await seed_player(test_db_session, vk_user_id=vk_user)
    await _seed_starting_group(test_db_session)
    await _seed_clock(test_db_session)
    await add_bot_state(test_db_session, 0)
    await test_db_session.commit()

    # (a) the real callback turns consent ALLOWED.
    resp = await client.post(
        CALLBACK_URL,
        json=vk_body(
            "message_allow",
            event_id="e1-allow",
            obj={"user_id": vk_user},
        ),
    )
    assert resp.status_code == 200
    assert resp.text == "ok"
    consent = await _consent_of(test_db_engine, player.id)
    assert consent.state == "ALLOWED"
    assert consent.state_source == "VK_EVENT"

    # (b) the gate passes on the stored ALLOWED — no VK call at all.
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(player.id),
        json=_nation_body(),
    )
    assert resp.status_code == 201
    assert fake.requests == []

    # Issue 7 (T26): the creation already queued the «nation_created»
    # reply; the first deliver sends it and the persistent keyboard
    # resolves to MEMBER (the nation exists at send time).
    await _deliver(test_db_engine, runtime)
    (created_send,) = fake.send_requests()
    created_form = _send_form(created_send)
    assert created_form["peer_ids"] == str(vk_user)
    assert created_form["message"] == (
        "Государство «Государство Тестовое» создано. Кнопки внизу "
        "обновлены: теперь доступны «Статус» и «Помощь»."
    )
    created_keyboard = form_keyboard(created_send)
    assert created_keyboard["inline"] is False
    assert _button_labels(created_keyboard) == ["Статус", "Помощь"]

    # (c)+(d) real tick, watcher enqueue, claim + send.
    await _tick(test_db_engine)
    await _watch(test_db_engine, config)
    (row,) = await _digest_rows(test_db_engine)
    assert row.player_id == player.id
    assert row.event_key == "turn:1"
    assert row.status == "PENDING"

    await _deliver(test_db_engine, runtime)

    # (e) exactly one digest send after the creation message.
    sends = fake.send_requests()
    assert len(sends) == 2
    send = sends[1]
    form = _send_form(send)
    assert form["peer_ids"] == str(vk_user)
    row = (await _digest_rows(test_db_engine))[0]
    assert form["random_id"] == str(row.random_id)
    assert row.status == "SENT"
    assert row.vk_message_id == 4242
    assert row.sent_at is not None

    clock_next_tick = await _next_tick(test_db_engine)
    expected_text = _expected(
        config.types["TICK_DIGEST"].text,
        {
            "turn": 1,
            "game_date": compute_game_date(1, CORE_CONFIG).isoformat(),
            "nation_name": "Государство Тестовое",
            "province_count": 2,
            "next_tick_time": format_game_time(
                clock_next_tick, TZ_NAME
            ),
        },
        config,
    )
    assert form["message"] == expected_text

    keyboard = form_keyboard(send)
    assert keyboard["one_time"] is False
    assert keyboard["inline"] is False
    assert _button_labels(keyboard) == ["Статус", "Помощь"]


async def _next_tick(engine) -> datetime:
    async with make_session_factory(engine)() as session:
        value = (
            await session.execute(
                select(GameClock.next_tick_at).where(GameClock.id == 1)
            )
        ).scalar_one()
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# E2 — idempotence (CAS + dedup + stored random_id)
# ---------------------------------------------------------------------------


async def test_e2_digest_sent_once_under_repeats(
    bot_started, file_db_engine
):
    """T1/INV-B5: concurrent watchers claim the turn once; repeats of
    watcher and sender leave exactly one row, one send, turn == 1."""
    config = bot_started
    sf = make_session_factory(file_db_engine)
    async with sf() as session:
        await _seed_clock(session)
        await add_bot_state(session, 0)
        await add_member(session, consent="ALLOWED", vk_user_id=660102)
        await session.commit()

    await _tick(file_db_engine)

    env = read_bot_env()
    fake = FakeVk()
    fake.respond_send_ok(message_id=9001)
    runtime = BotRuntime(
        config, env, sf, transport=fake.transport
    )
    runtime.prepare()
    try:
        # Two watcher passes racing on separate connections: the CAS
        # hands the turn to exactly one of them.
        await asyncio.gather(
            digest_watcher_step(sf, config),
            digest_watcher_step(sf, config),
        )
        rows = await _digest_rows(file_db_engine)
        assert len(rows) == 1
        assert rows[0].event_key == "turn:1"
        assert await _digest_turn(file_db_engine) == 1

        await _deliver(file_db_engine, runtime)
        assert len(fake.send_requests()) == 1
        assert (await _digest_rows(file_db_engine))[0].status == "SENT"

        # Watcher again + sender again for the same turn: no-op.
        await _watch(file_db_engine, config)
        await _deliver(file_db_engine, runtime)
        assert len(await _digest_rows(file_db_engine)) == 1
        assert len(fake.send_requests()) == 1
        assert await _digest_turn(file_db_engine) == 1
    finally:
        await runtime.aclose()


# ---------------------------------------------------------------------------
# E3 — registration consent gate
# ---------------------------------------------------------------------------


async def test_e3_denied_blocks_failopen_and_off(
    client,
    bot_started,
    consent_required,
    test_db_engine,
    test_db_session,
    fake_vk_runtime,
    caplog,
    monkeypatch,
):
    """T21: explicit VK denial -> durable DENIED + 403 twice with one
    VK call; VK outage fails open; flag off registers without VK."""
    import logging

    import modules._02_bot.startup as startup_mod

    fake, _runtime = fake_vk_runtime

    # (a) VK answers is_allowed=0 -> 403 CONSENT_REQUIRED, DENIED stored.
    fake.respond_allowed(False)
    denied = await seed_player(test_db_session, vk_user_id=660103)
    await _seed_starting_group(
        test_db_session, 1001, 1002, 1003, 1004, 1005, 1006
    )
    await test_db_session.commit()

    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(denied.id),
        json=_nation_body(),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "CONSENT_REQUIRED"
    assert len(fake.requests) == 1
    assert fake.requests[0].url.path.endswith(
        "messages.isMessagesFromGroupAllowed"
    )
    consent = await _consent_of(test_db_engine, denied.id)
    assert consent.state == "DENIED"
    assert consent.last_checked_at is not None
    async with make_session_factory(test_db_engine)() as session:
        assert (
            await session.execute(
                select(func.count())
                .select_from(Nation)
                .where(Nation.owner_player_id == denied.id)
            )
        ).scalar_one() == 0
        claimed = (
            await session.execute(
                select(func.count())
                .select_from(Province)
                .where(Province.nation_id.is_not(None))
            )
        ).scalar_one()
        assert claimed == 0
    # Second attempt inside the min interval: still 403, no new VK call.
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(denied.id),
        json=_nation_body(),
    )
    assert resp.status_code == 403
    assert len(fake.requests) == 1

    # (b) VK unreachable -> the gate fails open, nation is created.
    for _ in range(3):
        fake.fail_connect()
    lucky = await seed_player(test_db_session, vk_user_id=660104)
    await test_db_session.commit()
    with caplog.at_level(logging.WARNING):
        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(lucky.id),
            json=_nation_body(
                name="Государство Второе",
                color="#112233",
                province_ids=(1003, 1004),
            ),
        )
    assert resp.status_code == 201
    assert "registration_consent_check_skipped" in caplog.text

    # (c) required_for_registration=false -> no VK traffic at all.
    released = bot_started.model_copy(
        update={
            "consent": bot_started.consent.model_copy(
                update={"required_for_registration": False}
            )
        }
    )
    monkeypatch.setattr(startup_mod, "_bot_config", released)
    third = await seed_player(test_db_session, vk_user_id=660105)
    await test_db_session.commit()
    before = len(fake.requests)
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(third.id),
        json=_nation_body(
            name="Государство Третье",
            color="#445566",
            province_ids=(1005, 1006),
        ),
    )
    assert resp.status_code == 201
    assert len(fake.requests) == before


# ---------------------------------------------------------------------------
# E4 — VK outage does not touch the game
# ---------------------------------------------------------------------------


async def test_e4_vk_outage_tick_health_retry(
    client,
    bot_started,
    consent_required,
    test_db_engine,
    test_db_session,
    fake_vk_runtime,
):
    """T18: VK dead — tick completes, health unchanged, the digest
    survives PENDING and is sent once after recovery."""
    fake, runtime = fake_vk_runtime
    config = bot_started
    vk_user = 660106

    player = await seed_player(test_db_session, vk_user_id=vk_user)
    await add_consent(test_db_session, player.id, state="ALLOWED")
    await _seed_starting_group(test_db_session)
    await _seed_clock(test_db_session)
    await add_bot_state(test_db_session, 0)
    await test_db_session.commit()
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(player.id),
        json=_nation_body(),
    )
    assert resp.status_code == 201

    health_before = await client.get(HEALTH_URL)

    # Issue 7: the «nation_created» reply went out while VK was still
    # up; only the digest below faces the outage.
    await _deliver(test_db_engine, runtime)
    (created_send,) = fake.send_requests()
    assert _send_form(created_send)["message"] == _expected(
        config.dialog.texts.nation_created,
        {"nation_name": "Государство Тестовое"},
        config,
    )

    fake.fail_connect()
    await _tick(test_db_engine)
    assert await _clock_turn(test_db_engine) == 1
    await _watch(test_db_engine, config)
    await _deliver(test_db_engine, runtime)

    health_after = await client.get(HEALTH_URL)
    assert health_after.status_code == health_before.status_code
    assert health_after.json() == health_before.json()

    (row,) = await _digest_rows(test_db_engine)
    assert row.status == "PENDING"
    assert row.attempts == 1
    assert row.last_error_code == 0  # TRANSPORT
    assert aware(row.next_attempt_at) > datetime.now(timezone.utc)
    assert len(fake.send_requests()) == 2

    # VK recovers; with the clock past the backoff the same row —
    # same random_id — goes out exactly once more.
    fake.respond_send_ok(message_id=7777, peer_id=vk_user)
    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    await _deliver(test_db_engine, runtime, now=later)

    sends = fake.send_requests()
    assert len(sends) == 3
    row = (await _digest_rows(test_db_engine))[0]
    assert row.status == "SENT"
    assert row.vk_message_id == 7777
    assert _send_form(sends[2])["random_id"] == _send_form(
        sends[1]
    )["random_id"]


# ---------------------------------------------------------------------------
# E5 — consent lost mid-flight
# ---------------------------------------------------------------------------


async def test_e5_consent_lost_mid_flight(
    client,
    bot_started,
    test_db_engine,
    test_db_session,
    fake_vk_runtime,
):
    """T9/T14: VK 901 drops the row BLOCKED, flips consent DENIED; the
    next turn skips the player; message_allow re-enables digests."""
    fake, runtime = fake_vk_runtime
    config = bot_started
    vk_user = 660107

    async with make_session_factory(test_db_engine)() as session:
        await _seed_clock(session)
        await add_bot_state(session, 0)
        player = await add_member(
            session, consent="ALLOWED", vk_user_id=vk_user
        )
        await session.commit()

    fake.respond_recipient_error(901)
    await _tick(test_db_engine)
    await _watch(test_db_engine, config)
    await _deliver(test_db_engine, runtime)

    (row,) = await _digest_rows(test_db_engine)
    assert row.status == "DROPPED"
    assert row.drop_reason == "BLOCKED"
    consent = await _consent_of(test_db_engine, player.id)
    assert consent.state == "DENIED"
    assert consent.state_source == "VK_ERROR_901"
    # No retry for a consent loss.
    await _deliver(test_db_engine, runtime)
    assert len(fake.send_requests()) == 1

    # Next turn: the DENIED player gets no digest.
    await _tick(test_db_engine)
    await _watch(test_db_engine, config)
    assert len(await _digest_rows(test_db_engine)) == 1
    assert await _digest_turn(test_db_engine) == 2

    # The player re-allows messages; the following turn digests again —
    # and the old dropped row is not revived.
    resp = await client.post(
        CALLBACK_URL,
        json=vk_body(
            "message_allow",
            event_id="e5-allow",
            obj={"user_id": vk_user},
        ),
    )
    assert resp.status_code == 200
    assert (await _consent_of(test_db_engine, player.id)).state == (
        "ALLOWED"
    )

    fake.respond_send_ok(message_id=5555, peer_id=vk_user)
    await _tick(test_db_engine)
    await _watch(test_db_engine, config)
    rows = await _digest_rows(test_db_engine)
    assert len(rows) == 2
    dropped, pending = rows
    assert dropped.status == "DROPPED"
    assert pending.event_key == "turn:3"
    assert pending.status == "PENDING"

    await _deliver(test_db_engine, runtime)
    rows = await _digest_rows(test_db_engine)
    assert {r.status for r in rows} == {"DROPPED", "SENT"}
    assert len(fake.send_requests()) == 2


# ---------------------------------------------------------------------------
# E6 — dialog round trip
# ---------------------------------------------------------------------------


async def test_e6_dialog_round_trip(
    client,
    bot_started,
    consent_required,
    test_db_engine,
    test_db_session,
    fake_vk_runtime,
):
    """T14/T25: start (guest keyboard, both app-id variants), status,
    help inline links, plate cooldown — over the real callback and
    sender; message text is never stored."""
    fake, runtime = fake_vk_runtime
    config = bot_started
    vk_user = 660108
    sf = make_session_factory(test_db_engine)

    next_tick = datetime(2026, 3, 2, 21, 0, tzinfo=timezone.utc)
    player = await seed_player(test_db_session, vk_user_id=vk_user)
    await _seed_clock(
        test_db_session, turn=7, next_tick_at=next_tick
    )
    await test_db_session.commit()
    fake.respond_send_ok(message_id=1, peer_id=vk_user)

    # start: first contact -> start_guest with the GUEST keyboard
    # (open_app present because VK_APP_ID is set in the test env).
    resp = await client.post(
        CALLBACK_URL,
        json=message_new_body(
            vk_user, "e6-start", payload='{"command": "start"}'
        ),
    )
    assert resp.status_code == 200
    await _deliver(test_db_engine, runtime)
    (send,) = fake.send_requests()
    assert _send_form(send)["message"] == config.dialog.texts.start_guest
    keyboard = form_keyboard(send)
    assert _button_labels(keyboard) == [
        "Создать государство",
        "Помощь",
    ]
    open_app = keyboard["buttons"][0][0]["action"]
    assert open_app["type"] == "open_app"
    assert open_app["app_id"] == 777

    # Variant: VK_APP_ID unset -> the button disappears, «Помощь» stays.
    env_no_app = replace(read_bot_env(), app_id=None)
    runtime_no_app = BotRuntime(
        config, env_no_app, sf, transport=fake.transport
    )
    runtime_no_app.prepare()
    await client.post(
        CALLBACK_URL,
        json=message_new_body(
            vk_user, "e6-start-na", payload='{"command": "start"}'
        ),
    )
    await _deliver(test_db_engine, runtime_no_app)
    assert len(fake.send_requests()) == 2
    keyboard = form_keyboard(fake.send_requests()[-1])
    assert _button_labels(keyboard) == ["Помощь"]

    # Consent + nation through the real paths.
    await client.post(
        CALLBACK_URL,
        json=vk_body(
            "message_allow",
            event_id="e6-allow",
            obj={"user_id": vk_user},
        ),
    )
    await _seed_starting_group(test_db_session)
    await test_db_session.commit()
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(player.id),
        json=_nation_body(),
    )
    assert resp.status_code == 201

    # Issue 7 (T26): the creation itself queued the «nation_created»
    # reply — it goes out with the MEMBER keyboard right away.
    await _deliver(test_db_engine, runtime)
    send = fake.send_requests()[-1]
    assert _send_form(send)["message"] == (
        "Государство «Государство Тестовое» создано. Кнопки внизу "
        "обновлены: теперь доступны «Статус» и «Помощь»."
    )
    assert _button_labels(form_keyboard(send)) == ["Статус", "Помощь"]

    # status -> the fully rendered member status, MEMBER keyboard.
    await client.post(
        CALLBACK_URL,
        json=message_new_body(
            vk_user, "e6-status", payload='{"cmd": "status"}'
        ),
    )
    await _deliver(test_db_engine, runtime)
    send = fake.send_requests()[-1]
    expected_status = _expected(
        config.dialog.texts.status,
        {
            "nation_name": "Государство Тестовое",
            "leader_title": VALID_PROFILE["leader_title"],
            "leader_name": VALID_PROFILE["leader_name"],
            "province_count": 2,
            "turn": 7,
            "game_date": compute_game_date(7, CORE_CONFIG).isoformat(),
            "next_tick_time": format_game_time(next_tick, TZ_NAME),
        },
        config,
    )
    assert _send_form(send)["message"] == expected_status
    assert _button_labels(form_keyboard(send)) == [
        "Статус",
        "Помощь",
    ]

    # help -> inline keyboard with only the non-empty configured links.
    await client.post(
        CALLBACK_URL,
        json=message_new_body(
            vk_user, "e6-help", payload='{"cmd": "help"}'
        ),
    )
    await _deliver(test_db_engine, runtime)
    send = fake.send_requests()[-1]
    assert _send_form(send)["message"] == config.dialog.texts.help
    keyboard = form_keyboard(send)
    assert keyboard["inline"] is True
    actions = [
        b["action"] for row in keyboard["buttons"] for b in row
    ]
    # regulations_url is null in the shipped config — two links remain.
    assert [a["type"] for a in actions] == ["open_link", "open_link"]
    assert {a["link"] for a in actions} == {
        config.dialog.help.rules_url,
        config.dialog.help.admin_contact_url,
    }

    # Free text -> the plate once; a second one inside the cooldown
    # produces nothing new.
    await client.post(
        CALLBACK_URL,
        json=message_new_body(vk_user, "e6-t1", text="QZ-SECRET-911"),
    )
    await _deliver(test_db_engine, runtime)
    send = fake.send_requests()[-1]
    assert _send_form(send)["message"] == config.dialog.texts.plate
    sends_so_far = len(fake.send_requests())

    await client.post(
        CALLBACK_URL,
        json=message_new_body(vk_user, "e6-t2", text="QZ-SECRET-912"),
    )
    await _deliver(test_db_engine, runtime)
    assert len(fake.send_requests()) == sends_so_far

    # INV-B12: the player's message text is stored nowhere.
    async with sf() as session:
        outbox = (await session.execute(select(BotOutbox))).scalars().all()
        events = (
            await session.execute(select(BotVkEvent))
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
    assert "QZ-SECRET-911" not in blob
    assert "QZ-SECRET-912" not in blob


# ---------------------------------------------------------------------------
# E7 — bot off
# ---------------------------------------------------------------------------


async def test_e7_bot_off_is_invisible(
    client,
    bot_started_off,
    test_db_engine,
    test_db_session,
):
    """T17: OFF mode — callback 404s, status reports disabled,
    registration and the tick run normally, the queue stays empty."""
    player = await seed_player(test_db_session, vk_user_id=660109)
    await _seed_starting_group(test_db_session)
    await _seed_clock(test_db_session)
    await test_db_session.commit()

    resp = await client.post(
        CALLBACK_URL,
        json=vk_body(
            "message_allow",
            event_id="e7-allow",
            obj={"user_id": 660109},
        ),
    )
    assert resp.status_code == 404

    resp = await client.get(
        STATUS_URL, headers=bearer_headers(player.id)
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(player.id),
        json=_nation_body(),
    )
    assert resp.status_code == 201

    await _tick(test_db_engine)
    assert await _clock_turn(test_db_engine) == 1
    assert await _outbox_rows(test_db_engine) == []
    assert get_active_runtime() is None
    assert FakeVk().requests == []


# ---------------------------------------------------------------------------
# E8 — world reset
# ---------------------------------------------------------------------------


async def test_e8_world_reset_preserves_consents(
    client,
    bot_started,
    consent_required,
    test_db_engine,
    test_db_session,
    fake_vk_runtime,
    monkeypatch,
):
    """T16/INV-B14: the production reset path empties the queue and
    zeroes last_digest_turn while consents and the event journal
    survive; the next turn digests turn 1 again."""
    fake, runtime = fake_vk_runtime
    config = bot_started
    vk_user = 660110
    monkeypatch.setenv("ADMIN_ALLOW_RESET", "true")
    monkeypatch.setenv("ADMIN_VK_USER_IDS", str(vk_user))

    player = await seed_player(test_db_session, vk_user_id=vk_user)
    await _seed_starting_group(test_db_session)
    await _seed_clock(test_db_session)
    await add_bot_state(test_db_session, 0)
    await test_db_session.commit()

    # Journal row + ALLOWED consent through the real callback.
    await client.post(
        CALLBACK_URL,
        json=vk_body(
            "message_allow",
            event_id="e8-allow",
            obj={"user_id": vk_user},
        ),
    )
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(player.id),
        json=_nation_body(),
    )
    assert resp.status_code == 201
    await _tick(test_db_engine)
    await _watch(test_db_engine, config)
    assert len(await _digest_rows(test_db_engine)) == 1

    # The production reset: registered in lifespan order, executed
    # reversed (dependents first, 00_core last).
    AdminRegistry.clear_handlers()
    register_admin_hooks()  # 00_core
    AdminRegistry.register_reset("01_map", reset_ownership_log)
    register_bot_admin_hooks()  # 02_bot

    resp = await client.post(
        RESET_URL,
        headers=bearer_headers(player.id),
        json={"confirm": True},
    )
    assert resp.status_code == 200
    assert resp.json()["reset"] == ["02_bot", "01_map", "00_core"]

    assert await _outbox_rows(test_db_engine) == []
    assert await _digest_turn(test_db_engine) == 0
    consent = await _consent_of(test_db_engine, player.id)
    assert consent.state == "ALLOWED"
    async with make_session_factory(test_db_engine)() as session:
        events = (
            await session.execute(select(BotVkEvent))
        ).scalars().all()
        nation_count = (
            await session.execute(
                select(func.count()).select_from(Nation)
            )
        ).scalar_one()
    assert len(events) == 1
    assert nation_count == 0
    assert await _clock_turn(test_db_engine) == 0

    # The world restarts: provinces were freed, the kept ALLOWED lets
    # registration pass with no VK call, and turn 1 digests again.
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(player.id),
        json=_nation_body(),
    )
    assert resp.status_code == 201
    assert fake.requests == []

    # Issue 7: the kept ALLOWED consent queues the «nation_created»
    # reply for the recreated nation too — it goes out first.
    fake.respond_send_ok(message_id=3130, peer_id=vk_user)
    await _deliver(test_db_engine, runtime)
    (created_send,) = fake.send_requests()
    assert _send_form(created_send)["message"] == _expected(
        config.dialog.texts.nation_created,
        {"nation_name": "Государство Тестовое"},
        config,
    )

    fake.respond_send_ok(message_id=3131, peer_id=vk_user)
    await _tick(test_db_engine)
    await _watch(test_db_engine, config)
    (row,) = await _digest_rows(test_db_engine)
    assert row.event_key == "turn:1"
    assert row.status == "PENDING"
    await _deliver(test_db_engine, runtime)
    sends = fake.send_requests()
    assert len(sends) == 2
    assert _send_form(sends[1])["peer_ids"] == str(vk_user)
    assert (await _digest_rows(test_db_engine))[0].status == "SENT"


# ---------------------------------------------------------------------------
# E9 — status endpoints against the real flow
# ---------------------------------------------------------------------------


async def test_e9_status_and_refresh_flow(
    client,
    bot_started,
    consent_required,
    test_db_session,
    fake_vk_runtime,
):
    """T24: lazy check on GET, consent flip via callback, forced
    refresh, min-interval throttle on the rapid second POST."""
    fake, _runtime = fake_vk_runtime
    vk_user = 660111
    fake.respond_allowed(False)
    player = await seed_player(test_db_session, vk_user_id=vk_user)
    await test_db_session.commit()

    # UNKNOWN triggers exactly one lazy VK check -> DENIED stored.
    resp = await client.get(
        STATUS_URL, headers=bearer_headers(player.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["consent"] == "DENIED"
    assert body["stale"] is False
    assert body["throttled"] is False
    assert body["registration_requires_consent"] is True
    assert len(fake.requests) == 1
    assert fake.requests[0].url.path.endswith(
        "messages.isMessagesFromGroupAllowed"
    )

    # The player re-allows messages in VK; the callback flips the row.
    await client.post(
        CALLBACK_URL,
        json=vk_body(
            "message_allow",
            event_id="e9-allow",
            obj={"user_id": vk_user},
        ),
    )
    resp = await client.post(
        REFRESH_URL, headers=bearer_headers(player.id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["consent"] == "ALLOWED"
    # The lazy check seconds ago is still inside the min interval —
    # the forced refresh is throttled instead of calling VK again.
    assert body["throttled"] is True
    assert len(fake.requests) == 1

    resp = await client.post(
        REFRESH_URL, headers=bearer_headers(player.id)
    )
    assert resp.json()["throttled"] is True
    assert resp.json()["consent"] == "ALLOWED"
    assert len(fake.requests) == 1


# ---------------------------------------------------------------------------
# PostgreSQL mirrors of E1/E2 — SKIP LOCKED / ON CONFLICT differ there.
# ---------------------------------------------------------------------------


@pytest.mark.postgres
class TestPgMirror:
    """E1/E2 on real PostgreSQL (``DATABASE_URL_TEST``; skipped
    locally, covered by CI)."""

    @pytest_asyncio.fixture
    async def pg_bot(self, pg_url, pg_clean, monkeypatch, mini_map_config):
        """The live app on the PG test DB with the bot env configured;
        its lifespan runtime is stopped and replaced by a FakeVk one
        over the ``pg_db`` session maker."""
        import os
        from pathlib import Path

        from asgi_lifespan import LifespanManager
        from httpx import ASGITransport, AsyncClient
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        import modules._01_map.service as map_service_module
        import modules._02_bot.startup as startup_mod
        from main import app
        from modules._00_core.hooks import (
            restore_extension_points,
            snapshot_extension_points,
        )
        from tests.fixtures.postgres import _SKIP_REASON
        from tests.fixtures.provinces import MAP_MINI_DIR
        from tests.modules._00_core.test_router import (
            TEST_JWT_SECRET,
            TEST_VK_SECRET,
        )

        if not (os.environ.get("DATABASE_URL_TEST") or "").strip():
            pytest.skip(_SKIP_REASON)

        monkeypatch.setenv("DATABASE_URL", pg_url)
        monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
        monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
        monkeypatch.setenv("MAP_DATA_DIR", str(MAP_MINI_DIR))
        for name, value in {
            "BOT_ENABLED": "1",
            "VK_GROUP_ID": "12345",
            "VK_GROUP_TOKEN": "test-group-token",
            "VK_CALLBACK_SECRET": "test-callback-secret",
            "VK_CALLBACK_CONFIRMATION": "test-confirm",
            "VK_APP_ID": "777",
        }.items():
            monkeypatch.setenv(name, value)

        saved_views = AdminRegistry.get_state_view_hooks()
        saved_resets = AdminRegistry.get_reset_hooks()
        saved_handlers = {
            phase: list(handlers)
            for phase, handlers in TickOrchestrator._handlers.items()
        }
        saved_finalize = TickOrchestrator._finalize_callback
        saved_extensions = snapshot_extension_points()
        saved_map_service = map_service_module._instance
        saved_bot_config = startup_mod._bot_config

        engine = create_async_engine(pg_url)
        sf = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        # pg_clean does not cover the bot tables — wipe them here so the
        # two mirrors are independent.
        async with engine.begin() as conn:
            import sqlalchemy as sa

            for table in (
                "bot_outbox",
                "bot_consents",
                "bot_vk_events",
            ):
                await conn.execute(sa.text(f"DELETE FROM {table}"))
            await conn.execute(
                sa.text("UPDATE bot_state SET last_digest_turn = 0")
            )
        fake = FakeVk()
        try:
            async with LifespanManager(app) as manager:
                # Stop the real runtime (it has the real VK transport)
                # and install the FakeVk-bound twin on pg_db sessions.
                live = get_active_runtime()
                if live is not None:
                    await live.stop()
                runtime = BotRuntime(
                    startup_mod.get_bot_config(),
                    read_bot_env(),
                    sf,
                    transport=fake.transport,
                )
                runtime.prepare()
                install_runtime(runtime)
                transport = ASGITransport(app=manager.app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    yield client, fake, runtime, sf
        finally:
            install_runtime(None)
            await runtime.aclose()
            await engine.dispose()
            AdminRegistry._state_view_hooks.clear()
            AdminRegistry._state_view_hooks.update(saved_views)
            AdminRegistry._reset_hooks.clear()
            AdminRegistry._reset_hooks.update(saved_resets)
            TickOrchestrator._handlers.clear()
            TickOrchestrator._handlers.update(saved_handlers)
            TickOrchestrator._finalize_callback = saved_finalize
            restore_extension_points(saved_extensions)
            map_service_module._instance = saved_map_service
            startup_mod._bot_config = saved_bot_config

    async def test_pg_e1_full_flow(self, pg_bot, monkeypatch):
        """Provinces 1001/1002 come from the lifespan mini-map sync."""
        client, fake, runtime, sf = pg_bot
        config = runtime._config
        vk_user = 660201
        fake.respond_send_ok(message_id=6464, peer_id=vk_user)

        async with sf() as session:
            player = await seed_player(session, vk_user_id=vk_user)
            await session.commit()

        resp = await client.post(
            CALLBACK_URL,
            json=vk_body(
                "message_allow",
                event_id="pg-e1-allow",
                obj={"user_id": vk_user},
            ),
        )
        assert resp.status_code == 200

        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(player.id),
            json=_nation_body(),
        )
        assert resp.status_code == 201
        assert fake.requests == []

        # Issue 7: the «nation_created» reply is sent first.
        await _deliver_pg(sf, runtime)
        (created_send,) = fake.send_requests()
        assert _send_form(created_send)["peer_ids"] == str(vk_user)

        async with sf() as session:
            outcome = await run_scheduled_tick(session)
        assert outcome is TickOutcome.EXECUTED

        await digest_watcher_step(sf, config)
        await _deliver_pg(sf, runtime)

        sends = fake.send_requests()
        assert len(sends) == 2
        send = sends[1]
        assert _send_form(send)["peer_ids"] == str(vk_user)
        async with sf() as session:
            (row,) = (
                await session.execute(
                    select(BotOutbox).where(
                        BotOutbox.type_key == "TICK_DIGEST"
                    )
                )
            ).scalars().all()
        assert row.status == "SENT"
        assert row.vk_message_id == 6464

    async def test_pg_e2_concurrent_watcher_single_digest(
        self, pg_bot
    ):
        _client, fake, runtime, sf = pg_bot
        config = runtime._config
        fake.respond_send_ok(message_id=7)

        async with sf() as session:
            member = await add_member(
                session, consent="ALLOWED", vk_user_id=660202
            )
            await session.commit()

        async with sf() as session:
            outcome = await run_scheduled_tick(session)
        assert outcome is TickOutcome.EXECUTED

        await asyncio.gather(
            digest_watcher_step(sf, config),
            digest_watcher_step(sf, config),
        )
        async with sf() as session:
            rows = (
                await session.execute(
                    select(BotOutbox).where(
                        BotOutbox.type_key == "TICK_DIGEST"
                    )
                )
            ).scalars().all()
        assert len(rows) == 1
        assert rows[0].player_id == member.id

        await _deliver_pg(sf, runtime)
        assert len(fake.send_requests()) == 1
        # PG ON CONFLICT path: a repeated watcher pass enqueues nothing.
        await digest_watcher_step(sf, config)
        await _deliver_pg(sf, runtime)
        assert len(fake.send_requests()) == 1


async def _deliver_pg(sf, runtime, now: datetime | None = None):
    t = now or datetime.now(timezone.utc)
    async with sf() as session:
        groups = await claim_batch(
            session, runtime._config, runtime._env, t
        )
        await session.commit()
    await runtime._sender.process_groups(groups)
