"""
Player-deletion tests of module 00_core (admin test-player cleanup).

``PlayerService.delete_player`` runs the whole removal inside the
caller's transaction, all-or-nothing: the nation goes through
``NationService.delete`` (provinces freed, the real 01_map ownership
listener writes the journal), every registered player-delete hook
removes only its own module's rows, the ``players`` row goes last.

Real DB (SQLite via ``test_db_engine``), the REAL module hooks
registered through their own startup registrars — no mocks anywhere
(Anti-Mock Guard). The rollback scenario proves a raising hook leaves
every table untouched.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.admin.registry import AdminRegistry
from modules._00_core.exceptions import PlayerNotFoundError
from modules._00_core.hooks import (
    register_ownership_listener,
    register_player_delete_hook,
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.models import (
    Nation,
    NationApplication,
    NationApplicationProvince,
    NationImage,
    Player,
    Province,
    ScheduledAction,
)
from modules._00_core.service import PlayerService
from modules._01_map.hooks import ownership_log_listener
from modules._01_map.models import MapOwnershipLog
from modules._02_bot.admin_hooks import register_bot_admin_hooks
from modules._02_bot.models import BotConsent, BotOutbox
from modules._03_registry.admin_hooks import register_registry_admin_hooks
from modules._03_registry.models import RegistryVkProfile
from modules._04_orders.admin_hooks import register_orders_admin_hooks
from modules._04_orders.models import Order
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    ScheduledActionFactory,
    make_consent,
    make_order,
    make_outbox_row,
    make_vk_profile,
    utcnow,
)
from tests.fixtures.provinces import make_land_province

TARGET_VK_ID = 555001
OTHER_VK_ID = 555002


@pytest_asyncio.fixture
async def session_factory(test_db_engine):
    """Committed sessions over the test engine — like get_session_context."""
    return async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
def delete_wiring():
    """
    Register the REAL module player-delete hooks plus the 01_map
    ownership listener, then restore every class-level registry the
    registrations touched (extension points, AdminRegistry).
    """
    saved_extensions = snapshot_extension_points()
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_previews = AdminRegistry.get_player_preview_hooks()

    register_ownership_listener("01_map.ownership_log", ownership_log_listener)
    register_bot_admin_hooks()
    register_registry_admin_hooks()
    register_orders_admin_hooks()
    yield

    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    AdminRegistry._player_preview_hooks.clear()
    AdminRegistry._player_preview_hooks.update(saved_previews)
    restore_extension_points(saved_extensions)


async def _count(session: AsyncSession, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    for condition in conditions:
        query = query.where(condition)
    return (await session.execute(query)).scalar_one()


async def _seed(session: AsyncSession) -> dict:
    """
    The deletion target — player + nation + 2 provinces + one scheduled
    action + consent + outbox + profile + orders in all three roles —
    and a bystander player with the same kinds of rows who must survive
    untouched.
    """
    target = PlayerFactory.build(vk_user_id=TARGET_VK_ID, nations=[])
    other = PlayerFactory.build(vk_user_id=OTHER_VK_ID, nations=[])
    session.add_all([target, other])
    await session.flush()

    target_nation = NationFactory.build(
        owner=target,
        name="Цель",
        color_hex="#112233",
        provinces=[],
        scheduled_actions=[],
    )
    other_nation = NationFactory.build(
        owner=other,
        name="Свидетель",
        color_hex="#445566",
        provinces=[],
        scheduled_actions=[],
    )
    session.add_all([target_nation, other_nation])
    await session.flush()

    province_ids = []
    for pid in (3001, 3002):
        province = await make_land_province(session, id=pid)
        province.nation_id = target_nation.id
        province_ids.append(pid)
    other_province = await make_land_province(session, id=3003)
    other_province.nation_id = other_nation.id

    action = ScheduledActionFactory.build(nation=target_nation)
    session.add(action)

    await make_consent(session, target)
    await make_consent(session, other)
    await make_outbox_row(session, target)
    await make_outbox_row(session, target)
    await make_outbox_row(session, other)
    await make_vk_profile(session, target)
    await make_vk_profile(session, other)

    # A live application of the target with a province pick and an
    # uploaded picture — the deletion must remove all three rows
    # (0.13.0 unit 4); the bystander's application survives.
    target_application = NationApplication(
        id=str(uuid.uuid4()),
        owner_player_id=target.id,
        status="DRAFT",
        name="Target App",
        short_name="TApp",
        color_hex="#0C7CF4",
        submissions=0,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    other_application = NationApplication(
        id=str(uuid.uuid4()),
        owner_player_id=other.id,
        status="DRAFT",
        name="Other App",
        short_name="OApp",
        color_hex="#2B2DB0",
        submissions=0,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add_all([target_application, other_application])
    await session.flush()
    session.add(
        NationApplicationProvince(
            application_id=target_application.id,
            province_id=3001,
            position=0,
            is_reserved=False,
        )
    )
    session.add(
        NationImage(
            application_id=target_application.id,
            kind="flag",
            sha256="ee" * 32,
            full_bytes=b"x",
            thumb_bytes=b"y",
            byte_size=1,
            uploaded_by_player_id=target.id,
            uploaded_at=utcnow(),
        )
    )

    authored = await make_order(session, target, nation=target_nation)
    judged_open = await make_order(session, other, nation=other_nation, judge=target)
    judged_decided = await make_order(
        session,
        other,
        nation=other_nation,
        judge=target,
        submitted_at=utcnow(),
        verdict_at=utcnow() + timedelta(hours=1),
    )
    other_order = await make_order(session, other, nation=other_nation)
    await session.flush()

    return {
        "target_id": target.id,
        "other_id": other.id,
        "target_nation_id": target_nation.id,
        "other_nation_id": other_nation.id,
        "province_ids": province_ids,
        "other_province_id": other_province.id,
        "action_id": action.id,
        "authored_order_id": authored.id,
        "judged_open_order_id": judged_open.id,
        "judged_decided_order_id": judged_decided.id,
        "other_order_id": other_order.id,
        "target_application_id": target_application.id,
        "other_application_id": other_application.id,
    }


class TestPlayerDelete:
    """PlayerService.delete_player — the all-or-nothing admin cleanup."""

    @pytest.mark.asyncio
    async def test_removes_everything_and_frees_the_provinces(
        self, session_factory, delete_wiring
    ):
        async with session_factory() as session:
            ids = await _seed(session)
            await session.commit()

        async with session_factory() as session:
            await PlayerService.delete_player(session, ids["target_id"])
            await session.commit()

        async with session_factory() as session:
            # The player and the nation are gone.
            assert await _count(session, Player, Player.id == ids["target_id"]) == 0
            assert (
                await _count(session, Nation, Nation.id == ids["target_nation_id"]) == 0
            )

            # INV-6: the provinces are freed, never deleted.
            for pid in ids["province_ids"]:
                province = await session.get(Province, pid)
                assert province is not None
                assert province.nation_id is None
            other_province = await session.get(Province, ids["other_province_id"])
            assert other_province.nation_id == ids["other_nation_id"]

            # The ownership journal got one release entry per province
            # (prev = the deleted nation, new = NULL), written by the
            # real 01_map listener inside the deletion transaction.
            releases = (
                (
                    await session.execute(
                        select(MapOwnershipLog).where(
                            MapOwnershipLog.prev_nation_id == ids["target_nation_id"]
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert {row.province_id for row in releases} == set(ids["province_ids"])
            for row in releases:
                assert row.new_nation_id is None
                assert row.new_nation_name is None
                assert row.new_nation_color is None

            # The scheduled action is orphaned (nation_id NULL), not
            # deleted — NationService.delete's own rule.
            action = await session.get(ScheduledAction, ids["action_id"])
            assert action is not None
            assert action.nation_id is None

            # Every module's rows of the target are gone.
            assert (
                await _count(
                    session, BotConsent, BotConsent.player_id == ids["target_id"]
                )
                == 0
            )
            assert (
                await _count(
                    session, BotOutbox, BotOutbox.player_id == ids["target_id"]
                )
                == 0
            )
            assert (
                await _count(
                    session,
                    RegistryVkProfile,
                    RegistryVkProfile.player_id == ids["target_id"],
                )
                == 0
            )

            # Orders: authored and decided-as-judge rows are deleted;
            # the undecided judged order went back to the queue with
            # every assignment column NULL (the all-or-none CHECK).
            assert (
                await _count(session, Order, Order.id == ids["authored_order_id"]) == 0
            )
            assert (
                await _count(session, Order, Order.id == ids["judged_decided_order_id"])
                == 0
            )
            released = await session.get(Order, ids["judged_open_order_id"])
            assert released is not None
            assert released.judge_player_id is None
            assert released.distributed_at is None
            assert released.deadline_at is None
            assert released.reminder_at is None
            assert released.reminder_sent_at is None

            # The target's application, its province picks and its
            # pictures are gone with the player.
            assert (
                await _count(
                    session,
                    NationApplication,
                    NationApplication.id == ids["target_application_id"],
                )
                == 0
            )
            assert (
                await _count(
                    session,
                    NationApplicationProvince,
                    NationApplicationProvince.application_id
                    == ids["target_application_id"],
                )
                == 0
            )
            assert (
                await _count(
                    session,
                    NationImage,
                    NationImage.application_id == ids["target_application_id"],
                )
                == 0
            )

            # The bystander's rows are all untouched.
            assert await _count(session, Player, Player.id == ids["other_id"]) == 1
            assert (
                await _count(session, Nation, Nation.id == ids["other_nation_id"]) == 1
            )
            assert (
                await _count(
                    session, BotConsent, BotConsent.player_id == ids["other_id"]
                )
                == 1
            )
            assert (
                await _count(session, BotOutbox, BotOutbox.player_id == ids["other_id"])
                == 1
            )
            assert (
                await _count(
                    session,
                    RegistryVkProfile,
                    RegistryVkProfile.player_id == ids["other_id"],
                )
                == 1
            )
            other_order = await session.get(Order, ids["other_order_id"])
            assert other_order is not None
            assert (
                await _count(
                    session,
                    NationApplication,
                    NationApplication.id == ids["other_application_id"],
                )
                == 1
            )

    @pytest.mark.asyncio
    async def test_hook_failure_rolls_back_everything(
        self, session_factory, delete_wiring
    ):
        async with session_factory() as session:
            ids = await _seed(session)
            await session.commit()

        async def boom(session: AsyncSession, player_id: str) -> None:
            raise RuntimeError("hook exploded")

        # Registered LAST: every real hook runs before it, so the
        # rollback must undo their deletes as well.
        register_player_delete_hook("test.boom", boom)

        with pytest.raises(RuntimeError, match="hook exploded"):
            async with session_factory() as session:
                async with session.begin():
                    await PlayerService.delete_player(session, ids["target_id"])

        async with session_factory() as session:
            assert await _count(session, Player, Player.id == ids["target_id"]) == 1
            assert (
                await _count(session, Nation, Nation.id == ids["target_nation_id"]) == 1
            )
            for pid in ids["province_ids"]:
                province = await session.get(Province, pid)
                assert province.nation_id == ids["target_nation_id"]
            # No journal row survived the rollback.
            assert (
                await _count(
                    session,
                    MapOwnershipLog,
                    MapOwnershipLog.prev_nation_id == ids["target_nation_id"],
                )
                == 0
            )
            action = await session.get(ScheduledAction, ids["action_id"])
            assert action.nation_id == ids["target_nation_id"]
            assert (
                await _count(
                    session, BotConsent, BotConsent.player_id == ids["target_id"]
                )
                == 1
            )
            assert (
                await _count(
                    session, BotOutbox, BotOutbox.player_id == ids["target_id"]
                )
                == 2
            )
            assert (
                await _count(
                    session,
                    RegistryVkProfile,
                    RegistryVkProfile.player_id == ids["target_id"],
                )
                == 1
            )
            judged_open = await session.get(Order, ids["judged_open_order_id"])
            assert judged_open.judge_player_id == ids["target_id"]
            for order_id in (
                ids["authored_order_id"],
                ids["judged_decided_order_id"],
            ):
                assert await _count(session, Order, Order.id == order_id) == 1

    @pytest.mark.asyncio
    async def test_unknown_player_raises_not_found(
        self, session_factory, delete_wiring
    ):
        async with session_factory() as session:
            with pytest.raises(PlayerNotFoundError):
                await PlayerService.delete_player(session, str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_same_vk_id_logs_in_again_as_a_new_player(
        self, session_factory, delete_wiring
    ):
        """After deletion the VK account starts over: the next
        get_or_create mints a NEW player row with a fresh id."""
        async with session_factory() as session:
            ids = await _seed(session)
            await session.commit()

        async with session_factory() as session:
            await PlayerService.delete_player(session, ids["target_id"])
            await session.commit()

        async with session_factory() as session:
            again = await PlayerService.get_or_create(session, TARGET_VK_ID)
            assert again.id != ids["target_id"]
            assert again.vk_user_id == TARGET_VK_ID
