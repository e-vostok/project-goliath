"""
Nation-application («анкета») admin-side tests of module 00_core
(0.13.0 unit 5): the reviewer pick, accept/return/image-delete,
the worker pass (auto-accept + assignment) and the admin routes.

Real in-memory SQLite through ``test_db_engine`` — no mocks anywhere
(Anti-Mock Guard).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

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
    ApplicationSelfReviewError,
    ReturnCommentInvalidError,
)
from modules._00_core.models import (
    AdminAuditLog,
    AdminGrant,
    Nation,
    NationApplication,
    NationApplicationProvince,
    NationImage,
    Province,
)
from modules._00_core.reviewer import ReviewerCandidate, select_reviewer_v1
from modules._00_core.service import NationService
from tests.fixtures.factories import make_player
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import STARTING_GROUP, make_starting_group
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
    return async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture(autouse=True)
def env_secrets(monkeypatch):
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.delenv("ADMIN_VK_USER_IDS", raising=False)


@pytest_asyncio.fixture
async def client(test_db_session):
    async def _override_get_session():
        yield test_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _png(size=(1200, 800)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


async def _pending(session, player, **overrides) -> NationApplication:
    fields = {**_DRAFT, **overrides}
    await ApplicationService.save_draft(session, player.id, CORE_CONFIG, **fields)
    return await ApplicationService.submit(session, player.id, CORE_CONFIG)


async def _grant(session, player) -> AdminGrant:
    row = AdminGrant(player_id=player.id, granted_by_vk_user_id=1)
    session.add(row)
    await session.flush()
    return row


class TestReviewerPick:
    """Spec §5: the pure selector — load, age, applicant, nobody."""

    def test_select_reviewer_orders_and_excludes(self):
        applicant = "p-app"
        candidates = [
            ReviewerCandidate("p-load2", pending=0, last_assigned_at=None),
            ReviewerCandidate(
                "p-load1",
                pending=2,
                last_assigned_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            ReviewerCandidate(applicant, pending=0, last_assigned_at=None),
            ReviewerCandidate("p-load3", pending=0, last_assigned_at=None),
        ]
        # Least loaded wins; never-assigned counts oldest (τ = −∞);
        # the applicant is skipped despite a clean slate; ties break
        # on player_id.
        assert (
            select_reviewer_v1(applicant, candidates) == "p-load2"
        )
        assert select_reviewer_v1(applicant, candidates[2:3] * 0) is None
        # Only the applicant remains → nobody.
        assert (
            select_reviewer_v1(
                applicant, [c for c in candidates if c.player_id == applicant]
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_submit_assigns_admin_reviewer(self, session_factory):
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=620001)
            admin = await make_player(session, vk_user_id=620002)
            await _grant(session, admin)
            await make_starting_group(session)
            await session.commit()

        async with session_factory() as session:
            application = await _pending(session, player)
            assert application.reviewer_player_id == admin.id
            assert application.reviewer_assigned_at is not None

        async with session_factory() as session:
            # The applicant's own admin rights never self-assign.
            await _grant(session, player)
            other = await make_player(session, vk_user_id=620003)
            await make_starting_group(session)
            for pid in (1010, 1011, 1012, 1013, 1014):
                from tests.fixtures.provinces import make_land_province

                await make_land_province(session, id=pid)
            application2 = await _pending(
                session,
                other,
                name="Other Realm",
                short_name="OtherShort",
                color_hex="#2B2DB0",
                province_ids=[1010, 1011, 1012, 1013, 1014],
            )
            # other applicant: reviewer is an admin — either of the two.
            assert application2.reviewer_player_id in {admin.id, player.id}
            assert application2.reviewer_player_id != other.id


class TestAccept:
    """Spec §4: accept builds the nation in one transaction."""

    @pytest.mark.asyncio
    async def test_accept_creates_nation_moves_pictures(
        self, session_factory
    ):
        from modules._00_core import images as images_mod

        events = []

        async def collect(session, event):
            events.append(event.kind)

        from modules._00_core.hooks import register_application_listener

        register_application_listener("test.accept.collect", collect)

        async with session_factory() as session:
            player = await make_player(session, vk_user_id=620010)
            admin = await make_player(session, vk_user_id=620011)
            await _grant(session, admin)
            await make_starting_group(session)
            application = await ApplicationService.save_draft(
                session, player.id, CORE_CONFIG, **_DRAFT
            )
            processed = await images_mod.process_image_async(
                _png(), "flag", CORE_CONFIG.images
            )
            await ApplicationService.upload_image(
                session, application.id, player.id, "flag", processed
            )
            application = await ApplicationService.submit(
                session, player.id, CORE_CONFIG
            )
            await session.commit()

        async with session_factory() as session:
            application, nation = await ApplicationService.accept(
                session,
                application.id,
                CORE_CONFIG,
                decided_by_player_id=admin.id,
            )
            # The reserve never blocked its own accept (APP-1).
            assert application.status == "ACCEPTED"
            assert application.accepted_nation_id == nation.id
            assert application.auto_accepted is False
            assert application.decided_by_player_id == admin.id
            owned = (
                await session.execute(
                    select(func.count())
                    .select_from(NationApplicationProvince)
                    .where(
                        NationApplicationProvince.application_id
                        == application.id,
                        NationApplicationProvince.is_reserved.is_(True),
                    )
                )
            ).scalar_one()
            assert owned == 0
            flag = (
                await session.execute(
                    select(NationImage).where(
                        NationImage.nation_id == nation.id,
                        NationImage.kind == "flag",
                    )
                )
            ).scalar_one()
            assert flag.application_id is None
            assert nation.name == "Draftland"
            assert nation.owner_player_id == player.id
            await session.commit()

        assert "ACCEPTED" in events

    @pytest.mark.asyncio
    async def test_self_review_forbidden(self, session_factory):
        async with session_factory() as session:
            admin_player = await make_player(session, vk_user_id=620020)
            await _grant(session, admin_player)
            await make_starting_group(session)
            application = await _pending(session, admin_player)
            await session.commit()

        async with session_factory() as session:
            with pytest.raises(ApplicationSelfReviewError):
                await ApplicationService.accept(
                    session,
                    application.id,
                    CORE_CONFIG,
                    decided_by_player_id=admin_player.id,
                )
            with pytest.raises(ApplicationSelfReviewError):
                await ApplicationService.return_application(
                    session,
                    application.id,
                    admin_player.id,
                    "reason",
                    CORE_CONFIG,
                )


class TestReturn:
    """Spec §4 + APP-7: return needs a valid comment."""

    @pytest.mark.asyncio
    async def test_return_bad_comment_422(self, session_factory):
        async with session_factory() as session:
            player = await make_player(session, vk_user_id=620030)
            admin = await make_player(session, vk_user_id=620031)
            await _grant(session, admin)
            await make_starting_group(session)
            application = await _pending(session, player)
            await session.commit()

        async with session_factory() as session:
            for bad in (None, "", "   ", "x" * 301):
                with pytest.raises(ReturnCommentInvalidError):
                    await ApplicationService.return_application(
                        session,
                        application.id,
                        admin.id,
                        bad,
                        CORE_CONFIG,
                    )

    @pytest.mark.asyncio
    async def test_return_ok_via_route(self, client, test_db_session, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "620040")
        admin = await seed_player(test_db_session, vk_user_id=620040)
        player = await seed_player(test_db_session, vk_user_id=620041)
        await make_starting_group(test_db_session)
        application = await _pending(test_db_session, player)
        await test_db_session.commit()

        resp = await client.post(
            f"/api/v1/admin/applications/{application.id}/return",
            headers=bearer_headers(admin.id),
            json={"comment": "доделай историю"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "DRAFT"
        assert body["draft_reason"] == "returned"
        assert body["return_comment"] == "доделай историю"
        assert body["assigned_to_me"] is False

        journal = (
            await test_db_session.execute(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "application.return"
                )
            )
        ).scalar_one()
        assert journal.actor_vk_user_id == 620040


class TestWorkerPass:
    """Spec §6 + APP-4: auto-accept and the failed-check path."""

    @pytest.mark.asyncio
    async def test_pass_auto_accepts_and_fails(self, session_factory):
        events = []

        async def collect(session, event):
            events.append(event.kind)

        from modules._00_core.hooks import register_application_listener

        register_application_listener("test.pass.collect", collect)

        async with session_factory() as session:
            player_ok = await make_player(session, vk_user_id=620050)
            player_bad = await make_player(session, vk_user_id=620051)
            squatter = await make_player(session, vk_user_id=620052)
            await make_starting_group(session)
            for pid in (1010, 1011, 1012, 1013, 1014):
                from tests.fixtures.provinces import make_land_province

                await make_land_province(session, id=pid)
            app_ok = await _pending(session, player_ok)
            app_bad = await _pending(
                session,
                player_bad,
                name="Badland",
                short_name="Badland",
                color_hex="#2B2DB0",
                province_ids=[1010, 1011, 1012, 1013, 1014],
            )
            # Squatter's nation is seeded straight onto app_bad's
            # reserved provinces (the world the failed-check path
            # guards: provinces owned since the submit).
            squatter_nation = Nation(
                owner_player_id=squatter.id,
                name="Squatter",
                short_name="Squatter",
                color_hex="#058D1D",
                capital_province_id=1010,
                capital_name="Sq",
                created_at=datetime.now(UTC),
                created_turn=0,
            )
            session.add(squatter_nation)
            await session.flush()
            for pid in (1010, 1011, 1012, 1013, 1014):
                province = await session.get(Province, pid)
                province.nation_id = squatter_nation.id
            await session.flush()
            # Push both deadlines into the past.
            past = datetime.now(UTC) - timedelta(hours=1)
            app_ok.review_deadline_at = past
            app_bad.review_deadline_at = past
            await session.commit()

        stats = await ApplicationService.run_pass(session_factory, CORE_CONFIG)
        assert stats.auto_accepted == 1
        assert stats.auto_failed == 1
        assert stats.errors == 0

        async with session_factory() as session:
            ok_row = await session.get(NationApplication, app_ok.id)
            assert ok_row.status == "ACCEPTED"
            assert ok_row.auto_accepted is True
            assert ok_row.decided_by_player_id is None
            nation = (
                await session.execute(
                    select(Nation).where(
                        Nation.owner_player_id == player_ok.id
                    )
                )
            ).scalar_one()
            assert nation.name == "Draftland"
            bad_row = await session.get(NationApplication, app_bad.id)
            assert bad_row.status == "DRAFT"
            assert bad_row.draft_reason == "failed"
            assert bad_row.return_comment.startswith("Автоприём не удался")
            journal = (
                await session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == "application.auto_accept"
                    )
                )
            ).scalar_one()
            assert journal.actor_vk_user_id == 0

        assert "ACCEPTED" in events
        assert "RETURNED" in events


class TestAdminRoutes:
    """The admin list/detail/attention endpoints of Spec §8."""

    @pytest.mark.asyncio
    async def test_list_detail_accept_attention(
        self, client, test_db_session, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "620060")
        admin = await seed_player(test_db_session, vk_user_id=620060)
        player = await seed_player(test_db_session, vk_user_id=620061)
        await make_starting_group(test_db_session)
        application = await _pending(test_db_session, player)
        await test_db_session.commit()
        headers = bearer_headers(admin.id)

        # The lifespan did not run in this fixture — register the
        # module's admin hooks the way startup_core does.
        from modules._00_core.admin_hooks import register_admin_hooks

        register_admin_hooks()

        listing = await client.get(
            "/api/v1/admin/applications", headers=headers
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 1
        row = listing.json()["items"][0]
        assert row["short_name"] == application.short_name
        assert row["status"] == "PENDING"

        detail = await client.get(
            f"/api/v1/admin/applications/{application.id}", headers=headers
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["owner_vk_user_id"] == 620061
        # Submit picked the only admin (vk 620060) as this
        # application's reviewer — the tile is his.
        assert body["assigned_to_me"] is True

        attention = await client.get(
            "/api/v1/admin/attention", headers=headers
        )
        assert attention.status_code == 200, attention.text
        assert attention.json()["total"] == 1
        assert attention.json()["items"][0]["key"] == "applications_pending"

        accepted = await client.post(
            f"/api/v1/admin/applications/{application.id}/accept",
            headers=headers,
        )
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["status"] == "ACCEPTED"
        assert body["accepted_nation_id"]

        again = await client.post(
            f"/api/v1/admin/applications/{application.id}/accept",
            headers=headers,
        )
        assert again.status_code == 409, again.text
        assert again.json()["code"] == "APPLICATION_NOT_PENDING"

        journal = (
            await test_db_session.execute(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "application.accept"
                )
            )
        ).scalar_one()
        assert journal.actor_vk_user_id == 620060

    @pytest.mark.asyncio
    async def test_admin_image_delete(self, client, test_db_session, monkeypatch):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "620070")
        admin = await seed_player(test_db_session, vk_user_id=620070)
        player = await seed_player(test_db_session, vk_user_id=620071)
        await make_starting_group(test_db_session)
        application = await ApplicationService.save_draft(
            test_db_session, player.id, CORE_CONFIG, **_DRAFT
        )
        from modules._00_core import images as images_mod

        processed = await images_mod.process_image_async(
            _png(), "flag", CORE_CONFIG.images
        )
        await ApplicationService.upload_image(
            test_db_session, application.id, player.id, "flag", processed
        )
        application = await ApplicationService.submit(
            test_db_session, player.id, CORE_CONFIG
        )
        await test_db_session.commit()

        resp = await client.post(
            f"/api/v1/admin/applications/{application.id}/images/flag/delete",
            headers=bearer_headers(admin.id),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["images"]["flag"] is None

        journal = (
            await test_db_session.execute(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "application.image_delete"
                )
            )
        ).scalar_one()
        assert journal.actor_vk_user_id == 620070

        missing = await client.post(
            f"/api/v1/admin/applications/{application.id}/images/flag/delete",
            headers=bearer_headers(admin.id),
        )
        assert missing.status_code == 404
