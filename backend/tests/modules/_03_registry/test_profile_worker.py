"""
Tests for the profile worker cycle of 03_registry (Spec 2.3, 2.4).

Real in-memory DB through the fixtures; only the VK boundary is the
scripted ``FakeVk``. ``run_cycle`` gets its own sessions from
``session_factory`` — tests seed and assert through ``session_factory()``
sessions and never hold ``test_db_session`` open at the same time (the
shared ``:memory:`` pool serialises everything on one connection).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

import modules._03_registry.startup as startup_module
from modules._03_registry.models import RegistryVkProfile
from modules._03_registry.profile_worker import (
    WorkerMode,
    aware_utc,
    get_worker_mode,
    install_wake_event,
    run_cycle,
    start_profile_worker_if_ready,
)
from modules._03_registry.service import build_table
from modules._03_registry.vk_profiles import VkProfilesClient
from tests.fixtures.factories import make_vk_profile
from tests.fixtures.fake_vk import FakeVk
from tests.modules._03_registry.conftest import seed_player

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def make_client(fake: FakeVk, profiles) -> VkProfilesClient:
    return VkProfilesClient(profiles, "test-token", transport=fake.transport)


async def _profiles_by_player(session) -> dict[str, RegistryVkProfile]:
    rows = (
        (await session.execute(select(RegistryVkProfile)))
        .scalars()
        .all()
    )
    return {row.player_id: row for row in rows}


def _cells(built) -> dict[str, dict]:
    return {row.key: row.cells for row in built.rows}


class TestSuccessfulBatch:
    """Spec 2.4 steps 1–3 happy path: PENDING rows are created, the
    batch is fetched and the table shows the real names."""

    async def test_players_become_ok_and_table_shows_names(
        self, session_factory, registry_started
    ):
        profiles = registry_started.profiles
        async with session_factory() as session:
            await seed_player(session, 601001, created_at=NOW)
            await seed_player(
                session, 601002, created_at=NOW.replace(hour=13)
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_users_get(
            [
                {
                    "id": 601001,
                    "first_name": "Иван",
                    "last_name": "Петров",
                    "photo_50": "https://sun9-west.userapi.com/a.png",
                },
                {
                    "id": 601002,
                    "first_name": "Мария",
                    "last_name": "Смирнова",
                    "photo_50": "https://sun9-west.userapi.com/b.png",
                },
            ]
        )
        await run_cycle(session_factory, make_client(fake, profiles), profiles, NOW)

        async with session_factory() as session:
            rows = await _profiles_by_player(session)
            statuses = sorted(row.status for row in rows.values())
            assert statuses == ["OK", "OK"]
            ivan = next(
                row for row in rows.values() if row.first_name == "Иван"
            )
            assert ivan.photo_url == "https://sun9-west.userapi.com/a.png"
            assert aware_utc(ivan.next_attempt_at) == NOW + timedelta(
                hours=profiles.ttl_hours
            )

            cells = _cells(await build_table(session, "players"))
        assert cells["p1"]["player"] == {
            "name": "Иван Петров",
            "avatar_url": "https://sun9-west.userapi.com/a.png",
            "is_fallback": False,
        }
        assert cells["p2"]["player"]["name"] == "Мария Смирнова"
        assert len(fake.users_get_requests()) == 1


class TestUnavailable:
    """``deactivated`` and a missing id keep the earlier stored values
    (Spec 2.3, 3.4)."""

    async def test_unavailable_keeps_stored_name_and_photo(
        self, session_factory, registry_started
    ):
        profiles = registry_started.profiles
        async with session_factory() as session:
            p1 = await seed_player(session, 601101, created_at=NOW)
            p2 = await seed_player(
                session, 601102, created_at=NOW.replace(hour=13)
            )
            await make_vk_profile(
                session,
                p1,
                status="OK",
                first_name="Старый",
                last_name="Профиль",
                photo_url="https://old.userapi.com/a.png",
                next_attempt_at=NOW - timedelta(minutes=1),
            )
            await make_vk_profile(
                session,
                p2,
                status="PENDING",
                next_attempt_at=NOW - timedelta(minutes=1),
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_users_get(
            [
                {
                    "id": 601101,
                    "deactivated": "deleted",
                    "first_name": "DELETED",
                    "last_name": "ACCOUNT",
                }
                # 601102 absent from the response entirely.
            ]
        )
        await run_cycle(session_factory, make_client(fake, profiles), profiles, NOW)

        async with session_factory() as session:
            rows = await _profiles_by_player(session)
            r1, r2 = rows[p1.id], rows[p2.id]
            assert r1.status == "UNAVAILABLE"
            # The earlier stored name and photo stay (Spec 2.3).
            assert r1.first_name == "Старый"
            assert r1.last_name == "Профиль"
            assert r1.photo_url == "https://old.userapi.com/a.png"
            assert r2.status == "UNAVAILABLE"
            assert aware_utc(r1.next_attempt_at) == NOW + timedelta(
                hours=profiles.ttl_hours
            )

            cells = _cells(await build_table(session, "players"))
        # The stored name still shows; the avatar does not (not OK).
        assert cells["p1"]["player"] == {
            "name": "Старый Профиль",
            "avatar_url": None,
            "is_fallback": False,
        }


class TestBisect:
    """Error 30 for the full call, success on the halves: two OK, the
    bad one UNAVAILABLE (Spec 3.4)."""

    async def test_bisect_end_to_end(self, session_factory, registry_started):
        profiles = registry_started.profiles.model_copy(
            update={"batch_pause_seconds": 0}
        )
        async with session_factory() as session:
            players = [
                await seed_player(
                    session, 601201 + i, created_at=NOW.replace(hour=i)
                )
                for i in range(3)
            ]
            # Stagger due times into the past so all three are due at
            # NOW and the request order is deterministic.
            for i, player in enumerate(players):
                await make_vk_profile(
                    session,
                    player,
                    status="PENDING",
                    next_attempt_at=NOW - timedelta(seconds=3 - i),
                )
            await session.commit()

        fake = FakeVk()
        fake.respond_call_error(30)
        fake.respond_users_get(
            [{"id": 601201, "first_name": "А", "last_name": "Б"}]
        )
        fake.respond_users_get(
            [{"id": 601203, "first_name": "В", "last_name": "Г"}]
        )
        await run_cycle(session_factory, make_client(fake, profiles), profiles, NOW)

        forms = [fake.form_of(r) for r in fake.users_get_requests()]
        assert [f["user_ids"] for f in forms] == [
            "601201,601202,601203",
            "601201",
            "601202,601203",
        ]
        async with session_factory() as session:
            rows = await _profiles_by_player(session)
        assert rows[players[0].id].status == "OK"
        assert rows[players[1].id].status == "UNAVAILABLE"
        assert rows[players[2].id].status == "OK"


class TestFailures:
    """Batch-level failures defer the rows (Spec 2.3 last FSM row);
    an invalid key logs CRITICAL once per process (Spec 3.4)."""

    async def test_transport_5xx_defer_and_27_critical_once(
        self, session_factory, registry_started, caplog
    ):
        profiles = registry_started.profiles
        retry = timedelta(minutes=profiles.failure_retry_minutes)
        async with session_factory() as session:
            player = await seed_player(session, 601301, created_at=NOW)
            await session.commit()

        fake = FakeVk()
        client = make_client(fake, profiles)

        # Network error: the row keeps its status, only next_attempt_at moves.
        fake.fail_connect()
        await run_cycle(session_factory, client, profiles, NOW)
        async with session_factory() as session:
            row = (await _profiles_by_player(session))[player.id]
            assert row.status == "PENDING"
            assert row.first_name is None
            assert row.fetched_at is None
            assert aware_utc(row.next_attempt_at) == NOW + retry

        # HTTP 5xx after the retry window — same deferral.
        fake.push(httpx.Response(503, content=b"gateway"))
        await run_cycle(session_factory, client, profiles, NOW + retry)
        async with session_factory() as session:
            row = (await _profiles_by_player(session))[player.id]
            assert row.status == "PENDING"
            assert aware_utc(row.next_attempt_at) == NOW + 2 * retry

        # Error 27 over two cycles — one CRITICAL line per process.
        fake.respond_call_error(27)
        fake.respond_call_error(27)
        with caplog.at_level(
            logging.WARNING, logger="modules._03_registry.profile_worker"
        ):
            await run_cycle(
                session_factory, client, profiles, NOW + 2 * retry
            )
            await run_cycle(
                session_factory, client, profiles, NOW + 3 * retry
            )
        criticals = [
            r for r in caplog.records if r.levelno >= logging.CRITICAL
        ]
        assert len(criticals) == 1
        async with session_factory() as session:
            row = (await _profiles_by_player(session))[player.id]
            assert row.status == "PENDING"
            assert aware_utc(row.next_attempt_at) == NOW + 4 * retry


class TestTtl:
    """An OK profile is not requested again before ``ttl_hours``;
    a due one is (Spec 2.3)."""

    async def test_fresh_ok_not_refetched_due_one_is(
        self, session_factory, registry_started
    ):
        profiles = registry_started.profiles
        async with session_factory() as session:
            p1 = await seed_player(session, 601401, created_at=NOW)
            p2 = await seed_player(
                session, 601402, created_at=NOW.replace(hour=13)
            )
            await make_vk_profile(
                session,
                p1,
                status="OK",
                first_name="Иван",
                last_name="Петров",
                next_attempt_at=NOW + timedelta(hours=1),
            )
            await make_vk_profile(
                session,
                p2,
                status="OK",
                first_name="Мария",
                last_name="Смирнова",
                next_attempt_at=NOW - timedelta(minutes=1),
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_users_get(
            [{"id": 601402, "first_name": "Мария", "last_name": "Смирнова"}]
        )
        await run_cycle(session_factory, make_client(fake, profiles), profiles, NOW)

        requests = fake.users_get_requests()
        assert len(requests) == 1
        assert fake.form_of(requests[0])["user_ids"] == "601402"


class TestModes:
    """``enabled = false`` and a blank token: nothing is requested and
    the tables still open with fallback names (Spec 2.4)."""

    async def test_off_and_no_token_no_requests(
        self, session_factory, registry_started, monkeypatch, caplog
    ):
        config = registry_started
        async with session_factory() as session:
            await seed_player(session, 601501, created_at=NOW)
            await session.commit()

        # enabled = false -> OFF, no worker at all.
        off = config.model_copy(
            update={
                "profiles": config.profiles.model_copy(
                    update={"enabled": False}
                )
            }
        )
        monkeypatch.setattr(startup_module, "_registry_config", off)
        assert await start_profile_worker_if_ready(session_factory) is None
        assert get_worker_mode() is WorkerMode.OFF

        # enabled, but the token is blank -> NO_TOKEN, one WARNING.
        monkeypatch.setattr(startup_module, "_registry_config", config)
        monkeypatch.delenv("VK_GROUP_TOKEN", raising=False)
        with caplog.at_level(logging.WARNING):
            assert (
                await start_profile_worker_if_ready(session_factory) is None
            )
            # A repeated call must not warn twice (one per process).
            assert (
                await start_profile_worker_if_ready(session_factory) is None
            )
        assert get_worker_mode() is WorkerMode.NO_TOKEN
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "VK_GROUP_TOKEN" in r.getMessage()
        ]
        assert len(warnings) == 1

        # The tables still open with fallback names.
        async with session_factory() as session:
            cells = _cells(await build_table(session, "players"))
        assert cells["p1"]["player"]["name"] == "Игрок №1"
        assert cells["p1"]["player"]["is_fallback"] is True


class TestWake:
    """Spec 2.4 wake-up: a profile-less player sets the event; a row
    with a deferred retry does not."""

    async def test_table_build_sets_event_only_when_due(
        self, session_factory, registry_started
    ):
        event = asyncio.Event()
        install_wake_event(event)

        async with session_factory() as session:
            player = await seed_player(session, 601601, created_at=NOW)
            await session.commit()
            await build_table(session, "players")
            assert event.is_set()

            # Only a deferred retry remains — no wake.
            await make_vk_profile(
                session,
                player,
                status="UNAVAILABLE",
                next_attempt_at=datetime.now(timezone.utc)
                + timedelta(hours=1),
            )
            await session.commit()
            event.clear()
            await build_table(session, "players")
            assert not event.is_set()
