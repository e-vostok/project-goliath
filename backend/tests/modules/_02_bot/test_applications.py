"""
Application messages of module 02_bot (Spec 4.8 — 0.13.0 unit 6).

Every case drives the real listener — registered by ``startup_bot()``
as ``02_bot.applications`` — through the real ``ApplicationService``
operations on a real in-memory DB; nothing is mocked (Anti-Mock
Guard). The outbox rows are checked per recipient, and the texts are
rendered with the real config templates and the stored variables.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules._02_bot.startup as startup_mod
from modules._00_core.application_service import ApplicationService
from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import (
    ApplicationEvent,
    run_application_listeners,
)
from modules._00_core.models import AdminGrant, NationApplication
from modules._02_bot.models import BotOutbox
from modules._02_bot.render import render
from modules._02_bot.startup import startup_bot
from tests.fixtures.factories import make_player
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import STARTING_GROUP, make_starting_group
from tests.modules._02_bot._issue3_support import (
    aware,
    make_session_factory,
)

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

_DRAFT = {
    "name": "Draftland",
    "short_name": "Draftland",
    "color_hex": "#0C7CF4",
    "province_ids": list(STARTING_GROUP),
    "capital_province_id": None,
    "capital_name": "Draftburg",
    **VALID_PROFILE,
}

_GENITIVE_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


@pytest.fixture(autouse=True)
def _no_env_admins(monkeypatch):
    """No env admin allowlist — only granted rows make reviewers."""
    monkeypatch.delenv("ADMIN_VK_USER_IDS", raising=False)


@pytest_asyncio.fixture
async def session_factory(test_db_engine):
    """Committed sessions over the test engine."""
    return make_session_factory(test_db_engine)


@pytest.fixture
def started(bot_started, monkeypatch):
    """
    Real ``startup_bot()`` over the READY env — types registered, the
    listener wired. The registration consent gate is pinned off
    (``required_for_registration = false``) so submits never reach the
    VK check; the listener still sees every event.
    """
    config = bot_started.model_copy(
        update={
            "consent": bot_started.consent.model_copy(
                update={"required_for_registration": False}
            )
        }
    )
    monkeypatch.setattr(startup_mod, "_bot_config", config)
    return config


@pytest.fixture
def started_no_app_id(bot_env, monkeypatch):
    """READY env without ``VK_APP_ID`` — app_link returns None."""
    monkeypatch.delenv("VK_APP_ID")
    config = startup_bot()
    swapped = config.model_copy(
        update={
            "consent": config.consent.model_copy(
                update={"required_for_registration": False}
            )
        }
    )
    monkeypatch.setattr(startup_mod, "_bot_config", swapped)
    return swapped


async def _grant(session: AsyncSession, player) -> None:
    session.add(AdminGrant(player_id=player.id, granted_by_vk_user_id=1))
    await session.flush()


async def _pending(session: AsyncSession, player) -> NationApplication:
    await ApplicationService.save_draft(
        session, player.id, CORE_CONFIG, **_DRAFT
    )
    return await ApplicationService.submit(session, player.id, CORE_CONFIG)


async def _outbox(session: AsyncSession) -> list[BotOutbox]:
    return list(
        (
            await session.execute(select(BotOutbox).order_by(BotOutbox.id))
        ).scalars().all()
    )


def _expected_deadline(moment) -> str:
    """«1 ноября, 14:20» — computed independently in Europe/Moscow."""
    local = aware(moment).astimezone(ZoneInfo("Europe/Moscow"))
    return f"{local.day} {_GENITIVE_MONTHS[local.month - 1]}, {local:%H:%M}"


class TestMapping:
    """Spec 4.8: every event kind through the real listener."""

    async def test_submitted_writes_applicant_and_reviewer(
        self, started, session_factory
    ):
        """SUBMITTED -> APPLICATION_RECEIVED to the applicant plus
        APPLICATION_REVIEW_REQUEST to the reviewer the event carries;
        a repeated delivery writes nothing (dedup UNIQUE)."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770011, consent_state="ALLOWED"
            )
            reviewer = await make_player(
                session, vk_user_id=770012, consent_state="ALLOWED"
            )
            await _grant(session, reviewer)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, applicant)
            await session.commit()

        async with session_factory() as session:
            rows = await _outbox(session)
        assert len(rows) == 2

        received, request = rows
        deadline = _expected_deadline(application.review_deadline_at)
        assert received.player_id == applicant.id
        assert received.type_key == "APPLICATION_RECEIVED"
        assert received.kind == "NOTIFICATION"
        assert received.event_key == (
            f"application_APPLICATION_RECEIVED:{application.id}:1"
        )
        assert received.payload == {
            "nation_name": "Draftland",
            "application_link": "https://vk.com/app777#application",
            "deadline": deadline,
        }
        assert request.player_id == reviewer.id
        assert request.type_key == "APPLICATION_REVIEW_REQUEST"
        assert request.event_key == (
            f"application_APPLICATION_REVIEW_REQUEST:{application.id}:1"
        )
        assert request.payload == {
            "nation_name": "Draftland",
            "application_link": (
                f"https://vk.com/app777#application/{application.id}"
            ),
            "deadline": deadline,
        }
        # The texts render verbatim with the stored variables.
        assert (
            render(started.types["APPLICATION_RECEIVED"].text, received.payload)
            == (
                "Анкета государства «Draftland» получена. Администратор "
                f"рассмотрит её не позже {deadline} (МСК); если ответа "
                "не будет, анкета примется сама. Посмотреть или отменить "
                "анкету: https://vk.com/app777#application"
            )
        )
        assert (
            render(
                started.types["APPLICATION_REVIEW_REQUEST"].text,
                request.payload,
            )
            == (
                "Поступила анкета государства «Draftland». Откройте её и "
                f"примите или верните с причиной до {deadline} (МСК): "
                f"https://vk.com/app777#application/{application.id} Если "
                "решения не будет, анкета примется автоматически."
            )
        )

        # The same SUBMITTED event delivered again writes nothing.
        async with session_factory() as session:
            await run_application_listeners(
                session,
                ApplicationEvent(
                    kind="SUBMITTED",
                    application_id=application.id,
                    owner_player_id=applicant.id,
                    reviewer_player_id=reviewer.id,
                ),
            )
            await session.commit()
        async with session_factory() as session:
            assert len(await _outbox(session)) == 2

    async def test_submitted_without_reviewer_then_assigned(
        self, started, session_factory
    ):
        """SUBMITTED without a reviewer writes the applicant only; the
        worker's later ASSIGNED writes the review request to the
        reviewer — never to the applicant."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770021, consent_state="ALLOWED"
            )
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, applicant)
            assert application.reviewer_player_id is None
            await session.commit()

        async with session_factory() as session:
            rows = await _outbox(session)
        (received,) = rows
        assert received.player_id == applicant.id
        assert received.type_key == "APPLICATION_RECEIVED"

        async with session_factory() as session:
            reviewer = await make_player(
                session, vk_user_id=770022, consent_state="ALLOWED"
            )
            await _grant(session, reviewer)
            await session.commit()

        stats = await ApplicationService.run_pass(session_factory, CORE_CONFIG)
        assert stats.reviewers_assigned == 1

        async with session_factory() as session:
            rows = await _outbox(session)
        assert len(rows) == 2
        request = rows[1]
        assert request.player_id == reviewer.id
        assert request.type_key == "APPLICATION_REVIEW_REQUEST"
        assert request.event_key == (
            f"application_APPLICATION_REVIEW_REQUEST:{application.id}:1"
        )
        assert request.payload == {
            "nation_name": "Draftland",
            "application_link": (
                f"https://vk.com/app777#application/{application.id}"
            ),
            "deadline": _expected_deadline(application.review_deadline_at),
        }

    async def test_returned_writes_reason(self, started, session_factory):
        """RETURNED -> APPLICATION_RETURNED to the applicant carrying
        the reason as ``comment``."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770031, consent_state="ALLOWED"
            )
            decider = await make_player(session, vk_user_id=770032)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, applicant)
            await session.commit()

        async with session_factory() as session:
            await ApplicationService.return_application(
                session,
                application.id,
                decider.id,
                "Нет герба в анкете",
                CORE_CONFIG,
            )
            await session.commit()

        async with session_factory() as session:
            rows = await _outbox(session)
        assert len(rows) == 2
        returned = rows[1]
        assert returned.player_id == applicant.id
        assert returned.type_key == "APPLICATION_RETURNED"
        assert returned.event_key == (
            f"application_APPLICATION_RETURNED:{application.id}:1"
        )
        assert returned.payload == {
            "nation_name": "Draftland",
            "application_link": "https://vk.com/app777#application",
            "comment": "Нет герба в анкете",
        }
        assert (
            render(started.types["APPLICATION_RETURNED"].text, returned.payload)
            == (
                "Анкета государства «Draftland» возвращена на доработку. "
                "Причина: Нет герба в анкете Исправьте анкету и отправьте "
                "её снова: https://vk.com/app777#application"
            )
        )

    async def test_accepted_writes_created(self, started, session_factory):
        """ACCEPTED (administrator's decision) -> APPLICATION_ACCEPTED
        to the applicant."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770041, consent_state="ALLOWED"
            )
            decider = await make_player(session, vk_user_id=770042)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, applicant)
            await session.commit()

        async with session_factory() as session:
            await ApplicationService.accept(
                session,
                application.id,
                CORE_CONFIG,
                decided_by_player_id=decider.id,
            )
            await session.commit()

        async with session_factory() as session:
            rows = await _outbox(session)
        assert len(rows) == 2
        accepted = rows[1]
        assert accepted.player_id == applicant.id
        assert accepted.type_key == "APPLICATION_ACCEPTED"
        assert accepted.event_key == (
            f"application_APPLICATION_ACCEPTED:{application.id}:1"
        )
        assert accepted.payload == {
            "nation_name": "Draftland",
            "application_link": "https://vk.com/app777#application",
        }

    async def test_auto_accept_writes_auto(self, started, session_factory):
        """ACCEPTED with ``auto`` -> APPLICATION_ACCEPTED_AUTO."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770051, consent_state="ALLOWED"
            )
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, applicant)
            await session.commit()

        async with session_factory() as session:
            await ApplicationService.accept(
                session,
                application.id,
                CORE_CONFIG,
                decided_by_player_id=None,
                auto=True,
            )
            await session.commit()

        async with session_factory() as session:
            rows = await _outbox(session)
        assert len(rows) == 2
        accepted = rows[1]
        assert accepted.player_id == applicant.id
        assert accepted.type_key == "APPLICATION_ACCEPTED_AUTO"
        assert accepted.event_key == (
            f"application_APPLICATION_ACCEPTED_AUTO:{application.id}:1"
        )
        assert accepted.payload == {
            "nation_name": "Draftland",
            "application_link": "https://vk.com/app777#application",
        }

    async def test_cancelled_writes_nothing(self, started, session_factory):
        """CANCELLED -> nothing: the outbox keeps only the SUBMITTED row."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770061, consent_state="ALLOWED"
            )
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            await _pending(session, applicant)
            await session.commit()

        async with session_factory() as session:
            await ApplicationService.cancel(session, applicant.id)
            await session.commit()

        async with session_factory() as session:
            rows = await _outbox(session)
        (received,) = rows
        assert received.type_key == "APPLICATION_RECEIVED"


class TestSkips:
    """Spec 4.8: the silent paths — consent, VK_APP_ID, resubmission."""

    async def test_no_consent_writes_nothing_but_submit_succeeds(
        self, started, session_factory
    ):
        """A player without consent gets no row and the submission
        itself never fails (the shield and the panel stay the
        administrator's channels)."""
        async with session_factory() as session:
            applicant = await make_player(session, vk_user_id=770071)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, applicant)
            assert application.status == "PENDING"
            await session.commit()

        async with session_factory() as session:
            assert await _outbox(session) == []

    async def test_no_app_id_writes_nothing(
        self, started_no_app_id, session_factory, caplog
    ):
        """Without VK_APP_ID there is no link to send: nothing is
        enqueued and one warning is logged (like 04_orders)."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770081, consent_state="ALLOWED"
            )
            await make_starting_group(session)
            await session.commit()

        with caplog.at_level(logging.WARNING):
            async with session_factory() as session:
                application = await _pending(session, applicant)
                await session.commit()

        assert "application_notification_skipped_no_app_id" in caplog.text
        async with session_factory() as session:
            assert await _outbox(session) == []
        # The submission still landed PENDING.
        assert application.status == "PENDING"

    async def test_resubmission_writes_again(self, started, session_factory):
        """The dedup key carries ``submissions``: a return followed by
        a resubmit writes the applicant again under the new count."""
        async with session_factory() as session:
            applicant = await make_player(
                session, vk_user_id=770091, consent_state="ALLOWED"
            )
            decider = await make_player(session, vk_user_id=770092)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, applicant)
            await session.commit()

        async with session_factory() as session:
            await ApplicationService.return_application(
                session,
                application.id,
                decider.id,
                "Допишите историю",
                CORE_CONFIG,
            )
            await session.commit()

        async with session_factory() as session:
            application = await ApplicationService.submit(
                session, applicant.id, CORE_CONFIG
            )
            assert application.submissions == 2
            await session.commit()

        async with session_factory() as session:
            rows = await _outbox(session)
        assert [row.type_key for row in rows] == [
            "APPLICATION_RECEIVED",
            "APPLICATION_RETURNED",
            "APPLICATION_RECEIVED",
        ]
        assert rows[0].event_key == (
            f"application_APPLICATION_RECEIVED:{application.id}:1"
        )
        assert rows[2].event_key == (
            f"application_APPLICATION_RECEIVED:{application.id}:2"
        )
