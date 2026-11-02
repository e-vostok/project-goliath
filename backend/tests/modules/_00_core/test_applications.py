"""
Nation-application («анкета») tests of module 00_core (0.13.0 unit 4).

Real in-memory SQLite through ``test_db_engine`` — no mocks anywhere
(Anti-Mock Guard). Covers the draft/submit/cancel cycle, the APP-1
reserve against every other path, the listener registry and the
destructive paths.
"""

from __future__ import annotations

import io

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.db import get_session
from main import app
from modules._00_core.application_service import ApplicationService
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ApplicationNotEditableError,
    ApplicationNotFoundError,
    ApplicationNotPendingError,
    ColorTakenError,
    CoreDomainError,
    NameTakenError,
    NationAlreadyExistsError,
    ProvinceNotFoundError,
    ProvinceReservedError,
    ProvinceTakenError,
)
from modules._00_core.hooks import (
    STAGE_BEFORE_ALL,
    ApplicationEvent,
    register_application_listener,
    register_registration_check,
)
from modules._00_core.models import (
    Nation,
    NationApplication,
    NationApplicationProvince,
)
from modules._00_core.service import NationService, ProvinceService
from tests.fixtures.factories import NationFactory, PlayerFactory, make_player
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import (
    STARTING_GROUP,
    make_land_province,
    make_starting_group,
)
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    bearer_headers,
    seed_player,
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


@pytest_asyncio.fixture
async def session_factory(test_db_engine):
    """Committed sessions over the test engine — like get_session_context."""
    return async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture(autouse=True)
def env_secrets(monkeypatch):
    """Provide VK/JWT secrets for the live-client tests."""
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)


@pytest_asyncio.fixture
async def client(test_db_session):
    """HTTP client bound to the real app, backed by the test DB session."""

    async def _override_get_session():
        yield test_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _png(size: tuple[int, int], color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


async def _draft(session, player, **overrides) -> NationApplication:
    fields = {**_DRAFT, **overrides}
    return await ApplicationService.save_draft(
        session, player.id, CORE_CONFIG, **fields
    )


async def _pending(session, player, **overrides) -> NationApplication:
    await _draft(session, player, **overrides)
    return await ApplicationService.submit(session, player.id, CORE_CONFIG)


async def _count(session: AsyncSession, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    for condition in conditions:
        query = query.where(condition)
    return (await session.execute(query)).scalar_one()


class TestCycle:
    """DRAFT -> PENDING -> DRAFT -> PENDING (Spec applications §4)."""

    @pytest.mark.asyncio
    async def test_draft_submit_cancel_resubmit(self, session_factory):
        events: list[ApplicationEvent] = []

        async def collect(session: AsyncSession, event: ApplicationEvent) -> None:
            events.append(event)

        register_application_listener("test.collect", collect)

        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610001)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _draft(session, player)
            assert application.status == "DRAFT"
            assert application.submissions == 0
            rows = (
                await session.execute(select(NationApplicationProvince))
            ).scalars().all()
            assert {row.province_id for row in rows} == set(STARTING_GROUP)
            assert all(row.is_reserved is False for row in rows)
            await session.commit()

        async with session_factory() as session:
            application = await ApplicationService.submit(
                session, player.id, CORE_CONFIG
            )
            assert application.status == "PENDING"
            assert application.submissions == 1
            assert application.submitted_at is not None
            assert application.review_deadline_at is not None
            assert application.draft_reason is None
            reserved = (
                await session.execute(
                    select(NationApplicationProvince.province_id).where(
                        NationApplicationProvince.is_reserved.is_(True)
                    )
                )
            ).scalars().all()
            assert set(reserved) == set(STARTING_GROUP)
            await session.commit()

        async with session_factory() as session:
            application = await ApplicationService.cancel(session, player.id)
            assert application.status == "DRAFT"
            assert application.draft_reason == "cancelled"
            assert application.review_deadline_at is None
            assert application.reviewer_player_id is None
            await session.commit()

        async with session_factory() as session:
            application = await ApplicationService.submit(
                session, player.id, CORE_CONFIG
            )
            assert application.status == "PENDING"
            assert application.submissions == 2
            await session.commit()

        assert [event.kind for event in events] == [
            "SUBMITTED",
            "CANCELLED",
            "SUBMITTED",
        ]
        assert all(
            event.owner_player_id == player.id
            and event.application_id == application.id
            for event in events
        )

    @pytest.mark.asyncio
    async def test_draft_reserves_nothing(self, session_factory):
        """A DRAFT keeps its picks but reserves none of them — a nation
        can take the same name, colour and provinces until submit."""
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610002)
            other = await make_player(session, vk_user_id=610003)
            await make_starting_group(session)
            await _draft(session, player)
            await session.commit()

        async with session_factory() as session:
            nation = await NationService.create(
                session,
                owner_player_id=other.id,
                config=CORE_CONFIG,
                **_DRAFT,
            )
            assert nation.name == "Draftland"
            await session.commit()


class TestReserve:
    """APP-1: a PENDING application holds its name, colour, provinces."""

    @pytest.mark.asyncio
    async def test_pending_name_blocks_create(self, session_factory):
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610010)
            other = await make_player(session, vk_user_id=610011)
            await make_starting_group(session)
            await _pending(session, player)
            await session.commit()

        async with session_factory() as session:
            for pid in (1010, 1011, 1012, 1013, 1014):
                await make_land_province(session, id=pid)
            with pytest.raises(NameTakenError):
                await NationService.create(
                    session,
                    owner_player_id=other.id,
                    name="Draftland",
                    short_name="OtherName",
                    color_hex="#2B2DB0",
                    province_ids=[1010, 1011, 1012, 1013, 1014],
                    config=CORE_CONFIG,
                    **{
                        k: v
                        for k, v in VALID_PROFILE.items()
                        if k != "short_name"
                    },
                )

    @pytest.mark.asyncio
    async def test_pending_color_blocks_create_and_status(self, session_factory):
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610012)
            other = await make_player(session, vk_user_id=610013)
            await make_starting_group(session)
            await _pending(session, player)
            await session.commit()

        async with session_factory() as session:
            for pid in (1010, 1011, 1012, 1013, 1014):
                await make_land_province(session, id=pid)
            with pytest.raises(ColorTakenError):
                await NationService.create(
                    session,
                    owner_player_id=other.id,
                    name="Other Realm",
                    short_name="OtherShort",
                    color_hex="#0C7CF4",
                    province_ids=[1010, 1011, 1012, 1013, 1014],
                    config=CORE_CONFIG,
                    **{
                        k: v
                        for k, v in VALID_PROFILE.items()
                        if k != "short_name"
                    },
                )
            # The colour hint endpoint's decision sees the reserve too.
            assert (
                await NationService.color_status(session, "#0C7CF4", CORE_CONFIG)
                == "TAKEN"
            )

    @pytest.mark.asyncio
    async def test_pending_province_blocks_create_and_transfer(
        self, session_factory
    ):
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610014)
            other = await make_player(session, vk_user_id=610015)
            nation_owner = await make_player(session, vk_user_id=610016)
            await make_starting_group(session)
            await _pending(session, player)
            nation = NationFactory.build(
                owner=nation_owner,
                name="Other Realm",
                color_hex="#2B2DB0",
                provinces=[],
                scheduled_actions=[],
            )
            session.add(nation)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(ProvinceTakenError):
                await NationService.create(
                    session,
                    owner_player_id=other.id,
                    name="Third Realm",
                    short_name="ThirdShort",
                    color_hex="#058D1D",
                    province_ids=list(STARTING_GROUP),
                    config=CORE_CONFIG,
                    **{
                        k: v
                        for k, v in VALID_PROFILE.items()
                        if k != "short_name"
                    },
                )

        async with session_factory() as session:
            with pytest.raises(ProvinceReservedError):
                await ProvinceService.transfer(
                    session,
                    STARTING_GROUP[0],
                    nation.id,
                    config=CORE_CONFIG,
                )


class TestAuditFixes:
    """Lead AI audit of the unit-4 PR: the consent/nation gates of
    Spec §4 and the draft's province-existence check."""

    @pytest.mark.asyncio
    async def test_submit_runs_before_all_checks(self, session_factory):
        """A failing before_all check (e.g. missing bot consent,
        Spec 02_bot 3.10) refuses the submit — the draft stays DRAFT.
        The autouse process-state fixture restores the registry."""

        class _NoConsent(CoreDomainError):
            def __init__(self):
                super().__init__("consent missing", "TEST_NO_CONSENT")

        async def deny(session: AsyncSession, player_id: str) -> None:
            raise _NoConsent()

        register_registration_check(STAGE_BEFORE_ALL, "test.consent", deny)

        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610040)
            await make_starting_group(session)
            await _draft(session, player)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(_NoConsent):
                await ApplicationService.submit(
                    session, player.id, CORE_CONFIG
                )
            application = await ApplicationService.get_me(
                session, player.id
            )
            assert application.status == "DRAFT"

    @pytest.mark.asyncio
    async def test_submit_refused_when_nation_exists(self, session_factory):
        """An administrator may create the nation after the draft was
        saved — submit then answers NATION_ALREADY_EXISTS first."""
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610041)
            await make_starting_group(session)
            await _draft(session, player)
            nation = NationFactory.build(
                owner=player, provinces=[], scheduled_actions=[]
            )
            session.add(nation)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(NationAlreadyExistsError):
                await ApplicationService.submit(
                    session, player.id, CORE_CONFIG
                )

    @pytest.mark.asyncio
    async def test_draft_unknown_province_refused(self, session_factory):
        """A province id that does not exist is PROVINCE_NOT_FOUND,
        never a foreign-key 500 or a silent bad row."""
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610042)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(ProvinceNotFoundError):
                await _draft(
                    session,
                    player,
                    province_ids=[1001, 1002, 1003, 1004, 9999],
                )

    @pytest.mark.asyncio
    async def test_put_image_draft_ok_pending_409(self, client, test_db_session):
        """PUT /applications/me/images/{kind}: 200 on a DRAFT, 409
        APPLICATION_NOT_EDITABLE once the application is PENDING."""
        player = await seed_player(test_db_session)
        await make_starting_group(test_db_session)
        headers = bearer_headers(player.id)

        draft = await client.put(
            "/api/v1/applications/me", headers=headers, json=_DRAFT
        )
        assert draft.status_code == 200, draft.text

        ok = await client.put(
            "/api/v1/applications/me/images/flag",
            headers=headers,
            content=_png((1200, 800)),
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["kind"] == "flag"

        submitted = await client.post(
            "/api/v1/applications/me/submit", headers=headers
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "PENDING"

        refused = await client.put(
            "/api/v1/applications/me/images/flag",
            headers=headers,
            content=_png((1200, 800)),
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "APPLICATION_NOT_EDITABLE"


class TestGuards:
    """The state-machine refusals of Spec §2/§4."""

    @pytest.mark.asyncio
    async def test_get_me_missing_and_pending_not_editable(self, session_factory):
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610020)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            assert await ApplicationService.get_me(session, player.id) is None
            with pytest.raises(ApplicationNotFoundError):
                await ApplicationService.submit(session, player.id, CORE_CONFIG)
            await _pending(session, player)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(ApplicationNotEditableError):
                await _draft(session, player)
            with pytest.raises(ApplicationNotEditableError):
                await ApplicationService.submit(
                    session, player.id, CORE_CONFIG
                )

    @pytest.mark.asyncio
    async def test_cancel_requires_pending_and_nation_blocks_draft(
        self, session_factory
    ):
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610021)
            owner = await make_player(session, vk_user_id=610022)
            await make_starting_group(session)
            await _draft(session, player)
            nation = NationFactory.build(
                owner=owner, provinces=[], scheduled_actions=[]
            )
            session.add(nation)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(ApplicationNotPendingError):
                await ApplicationService.cancel(session, player.id)
            with pytest.raises(NationAlreadyExistsError):
                await _draft(
                    session, owner, name="Realm", short_name="Realm"
                )

    @pytest.mark.asyncio
    async def test_listener_failure_keeps_the_submit(self, session_factory):
        """A broken listener loses only its own SAVEPOINT writes — the
        PENDING transition stands (Spec §7)."""
        called: list[str] = []

        async def boom(session: AsyncSession, event: ApplicationEvent) -> None:
            raise RuntimeError("listener exploded")

        async def seen(session: AsyncSession, event: ApplicationEvent) -> None:
            called.append(event.kind)

        register_application_listener("test.boom", boom)
        register_application_listener("test.seen", seen)

        async with session_factory() as session:
            player = await make_player(session, vk_user_id=610030)
            await make_starting_group(session)
            await _draft(session, player)
            await session.commit()

        async with session_factory() as session:
            application = await ApplicationService.submit(
                session, player.id, CORE_CONFIG
            )
            await session.commit()

        assert application.status == "PENDING"
        assert called == ["SUBMITTED"]
