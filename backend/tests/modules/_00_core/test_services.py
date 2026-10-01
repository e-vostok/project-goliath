"""
Tests for 00_core domain services.

Tests PlayerService, NationService, and ScheduledActionService against
the real test database using factories. No mocking of state.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ColorTakenError,
    FrequencyCapExceededError,
    HistoryUrlInvalidError,
    LeaderNameInvalidError,
    LeaderTitleInvalidError,
    NameTakenError,
    NationAlreadyExistsError,
    NationNotFoundError,
    ProvinceCountOutOfRangeError,
    ProvinceNotFoundError,
    ProvinceTakenError,
)
from modules._00_core.models import Nation, Player, Province, ScheduledAction, ScheduledActionStatus
from modules._00_core.service import (
    FrequencyRule,
    NationService,
    PlayerService,
    ScheduledActionService,
)
from tests.fixtures.profile import VALID_PROFILE


class TestPlayerService:
    """Tests for PlayerService."""
    
    @pytest.mark.asyncio
    async def test_get_or_create_new_player(self, test_db_session):
        """Test that a new player is created when vk_user_id doesn't exist."""
        player = await PlayerService.get_or_create(test_db_session, vk_user_id=12345)
        
        assert player.vk_user_id == 12345
        assert player.id is not None
        
        # Verify it was persisted
        result = await test_db_session.execute(
            select(Player).where(Player.vk_user_id == 12345)
        )
        assert result.scalar_one() is not None
    
    @pytest.mark.asyncio
    async def test_get_or_create_existing_player(self, test_db_session):
        """Test that an existing player is returned when vk_user_id exists."""
        # Create a player first
        existing = Player(vk_user_id=999)
        test_db_session.add(existing)
        await test_db_session.flush()
        
        # Get or create should return the existing one
        player = await PlayerService.get_or_create(test_db_session, vk_user_id=999)
        
        assert player.id == existing.id
        assert player.vk_user_id == 999


class TestNationService:
    """Tests for NationService."""
    
    @pytest.fixture
    async def config(self):
        """Load the core config for tests."""
        return CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    
    async def _create_player(self, session, vk_user_id: int = 11111) -> Player:
        """Helper to create a player."""
        player = Player(vk_user_id=vk_user_id)
        session.add(player)
        await session.flush()
        return player
    
    async def _create_provinces(self, session, ids: list[int]) -> list[Province]:
        """Helper to create provinces."""
        provinces = [Province(id=pid, nation_id=None) for pid in ids]
        for p in provinces:
            session.add(p)
        await session.flush()
        return provinces
    
    @pytest.mark.asyncio
    async def test_create_nation_happy_path(self, test_db_session, config):
        """Test successful nation creation."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1, 2, 3])
        
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1, 2],
            config=config,
            **VALID_PROFILE,
        )
        
        assert nation.name == "Test Nation"
        assert nation.color_hex == "#FF0000"
        assert nation.owner_player_id == player.id
        
        # Verify provinces are assigned
        result = await test_db_session.execute(
            select(Province).where(Province.id.in_([1, 2]))
        )
        provinces = result.scalars().all()
        assert all(p.nation_id == nation.id for p in provinces)
    
    @pytest.mark.asyncio
    async def test_create_nation_inv1_player_already_has_nation(self, test_db_session, config):
        """Test INV-1: Player cannot have two nations."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1, 2])
        
        # Create first nation
        await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="First Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        
        # Try to create second nation - should fail
        with pytest.raises(NationAlreadyExistsError):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Second Nation",
                color_hex="#00FF00",
                province_ids=[2],
                config=config,
                **VALID_PROFILE,
            )
    
    @pytest.mark.asyncio
    async def test_create_nation_inv2_name_taken(self, test_db_session, config):
        """Test INV-2: Nation name must be unique."""
        player = await self._create_player(test_db_session, vk_user_id=11111)
        await self._create_provinces(test_db_session, [1, 2])
        
        # Create first nation
        await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Taken Name",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        
        # Create another player
        other_player = await self._create_player(test_db_session, vk_user_id=22222)
        
        # Try to create nation with same name - should fail
        with pytest.raises(NameTakenError):
            await NationService.create(
                test_db_session,
                owner_player_id=other_player.id,
                name="Taken Name",
                color_hex="#00FF00",
                province_ids=[2],
                config=config,
                **VALID_PROFILE,
            )
    
    @pytest.mark.asyncio
    async def test_create_nation_inv2_color_taken(self, test_db_session, config):
        """Test INV-2: Nation color must be unique."""
        player = await self._create_player(test_db_session, vk_user_id=11111)
        await self._create_provinces(test_db_session, [1, 2])
        
        # Create first nation
        await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="First Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        
        # Create another player
        other_player = await self._create_player(test_db_session, vk_user_id=22222)
        
        # Try to create nation with same color - should fail
        with pytest.raises(ColorTakenError):
            await NationService.create(
                test_db_session,
                owner_player_id=other_player.id,
                name="Second Nation",
                color_hex="#FF0000",
                province_ids=[2],
                config=config,
                **VALID_PROFILE,
            )
    
    @pytest.mark.asyncio
    async def test_create_nation_province_not_found(self, test_db_session, config):
        """Test that non-existent province raises error."""
        player = await self._create_player(test_db_session)
        
        with pytest.raises(ProvinceNotFoundError):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Test Nation",
                color_hex="#FF0000",
                province_ids=[999],  # Non-existent
                config=config,
                **VALID_PROFILE,
            )
    
    @pytest.mark.asyncio
    async def test_create_nation_province_taken(self, test_db_session, config):
        """Test that already-owned province raises error."""
        player = await self._create_player(test_db_session, vk_user_id=11111)
        other_player = await self._create_player(test_db_session, vk_user_id=22222)
        await self._create_provinces(test_db_session, [1, 2])
        
        # Create nation that owns province 1
        await NationService.create(
            test_db_session,
            owner_player_id=other_player.id,
            name="Other Nation",
            color_hex="#00FF00",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        
        # Try to create nation that also wants province 1
        with pytest.raises(ProvinceTakenError):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Test Nation",
                color_hex="#FF0000",
                province_ids=[1, 2],
                config=config,
                **VALID_PROFILE,
            )
    
    @pytest.mark.asyncio
    async def test_create_nation_province_count_out_of_range_min(self, test_db_session, config):
        """Test province count below minimum."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])
        
        with pytest.raises(ProvinceCountOutOfRangeError):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Test Nation",
                color_hex="#FF0000",
                province_ids=[],  # Below min (1)
                config=config,
                **VALID_PROFILE,
            )
    
    @pytest.mark.asyncio
    async def test_create_nation_province_count_out_of_range_max(self, test_db_session, config):
        """Test province count above maximum."""
        player = await self._create_player(test_db_session)
        
        # Create many provinces
        province_ids = list(range(1, 11))
        provinces = [Province(id=pid, nation_id=None) for pid in province_ids]
        for p in provinces:
            test_db_session.add(p)
        await test_db_session.flush()
        
        with pytest.raises(ProvinceCountOutOfRangeError):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Test Nation",
                color_hex="#FF0000",
                province_ids=province_ids,  # Above max (5)
                config=config,
                **VALID_PROFILE,
            )
    
    @pytest.mark.asyncio
    async def test_update_nation_name(self, test_db_session, config):
        """Test updating nation name."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])
        
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Old Name",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        
        updated = await NationService.update(
            test_db_session,
            nation_id=nation.id,
            name="New Name",
            config=config,
        )

        assert updated.name == "New Name"
        assert updated.color_hex == "#FF0000"
    
    @pytest.mark.asyncio
    async def test_update_nation_color(self, test_db_session, config):
        """Test updating nation color."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])
        
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        
        updated = await NationService.update(
            test_db_session,
            nation_id=nation.id,
            color_hex="#00FF00",
            config=config,
        )
        
        assert updated.name == "Test Nation"
        assert updated.color_hex == "#00FF00"
    
    @pytest.mark.asyncio
    async def test_update_nation_name_taken(self, test_db_session, config):
        """Test updating to a taken name."""
        player1 = await self._create_player(test_db_session, vk_user_id=11111)
        player2 = await self._create_player(test_db_session, vk_user_id=22222)
        await self._create_provinces(test_db_session, [1, 2])
        
        # Create two nations
        nation1 = await NationService.create(
            test_db_session,
            owner_player_id=player1.id,
            name="Nation 1",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        
        await NationService.create(
            test_db_session,
            owner_player_id=player2.id,
            name="Nation 2",
            color_hex="#00FF00",
            province_ids=[2],
            config=config,
            **VALID_PROFILE,
        )
        
        # Try to update nation1 to nation2's name
        with pytest.raises(NameTakenError):
            await NationService.update(
                test_db_session,
                nation_id=nation1.id,
                name="Nation 2",
                config=config,
            )
    
    @pytest.mark.asyncio
    async def test_update_nation_not_found(self, test_db_session, config):
        """Test updating non-existent nation."""
        with pytest.raises(NationNotFoundError):
            await NationService.update(
                test_db_session,
                nation_id="non-existent-id",
                name="New Name",
                config=config,
            )
    
    @pytest.mark.asyncio
    async def test_delete_nation_inv6(self, test_db_session, config):
        """Test INV-6: Deleting nation frees provinces instead of deleting them."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1, 2])
        
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1, 2],
            config=config,
            **VALID_PROFILE,
        )
        
        await NationService.delete(test_db_session, nation_id=nation.id)
        
        # Verify nation is deleted
        result = await test_db_session.execute(
            select(Nation).where(Nation.id == nation.id)
        )
        assert result.scalar_one_or_none() is None
        
        # Verify provinces are freed (nation_id is NULL)
        result = await test_db_session.execute(
            select(Province).where(Province.id.in_([1, 2]))
        )
        provinces = result.scalars().all()
        assert all(p.nation_id is None for p in provinces)
    
    @pytest.mark.asyncio
    async def test_delete_nation_orphans_pending_scheduled_actions(self, test_db_session, config):
        """Deleting a nation orphans its PENDING scheduled actions.

        INV-6-style: like freed provinces, the action row survives as an
        orphaned historical record (nation_id -> NULL), not deleted.
        """
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])

        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )

        action = await ScheduledActionService.submit(
            test_db_session,
            nation_id=nation.id,
            module_slug="test_module",
            action_type="test_action",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_TURN,
        )

        await NationService.delete(test_db_session, nation_id=nation.id)

        result = await test_db_session.execute(
            select(ScheduledAction).where(ScheduledAction.id == action.id)
        )
        orphaned = result.scalar_one()
        assert orphaned.nation_id is None
        assert orphaned.status == ScheduledActionStatus.PENDING

    @pytest.mark.asyncio
    async def test_delete_nation_orphans_applied_scheduled_actions(self, test_db_session, config):
        """Deleting a nation orphans its APPLIED scheduled actions too."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])

        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )

        action = await ScheduledActionService.submit(
            test_db_session,
            nation_id=nation.id,
            module_slug="test_module",
            action_type="test_action",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_TURN,
        )
        action.status = ScheduledActionStatus.APPLIED
        await test_db_session.flush()

        await NationService.delete(test_db_session, nation_id=nation.id)

        result = await test_db_session.execute(
            select(ScheduledAction).where(ScheduledAction.id == action.id)
        )
        orphaned = result.scalar_one()
        assert orphaned.nation_id is None
        assert orphaned.status == ScheduledActionStatus.APPLIED

    @pytest.mark.asyncio
    async def test_delete_nation_not_found(self, test_db_session):
        """Test deleting non-existent nation."""
        with pytest.raises(NationNotFoundError):
            await NationService.delete(
                test_db_session,
                nation_id="non-existent-id",
            )


class TestNationProfile:
    """Tests for the nation profile fields (Spec 1.1, INV-7/8/9)."""

    @pytest.fixture
    async def config(self):
        """Load the core config for tests."""
        return CoreConfig.from_yaml(CoreConfig.get_default_config_path())

    async def _create_player(self, session, vk_user_id: int = 11111) -> Player:
        player = Player(vk_user_id=vk_user_id)
        session.add(player)
        await session.flush()
        return player

    async def _create_provinces(self, session, ids: list[int]) -> None:
        for pid in ids:
            session.add(Province(id=pid, nation_id=None))
        await session.flush()

    async def _nation_count(self, session) -> int:
        result = await session.execute(select(Nation))
        return len(result.scalars().all())

    async def _province_is_free(self, session, province_id: int) -> bool:
        result = await session.execute(
            select(Province).where(Province.id == province_id)
        )
        return result.scalar_one().nation_id is None

    async def test_create_stores_normalized_profile(self, test_db_session, config):
        """Padded input is stored in its normalized (stripped) form."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])

        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            leader_name="  Ivan Grozny  ",
            leader_title="\tSupreme Ruler\n",
            history_url="  https://vk.com/@goliath-history  ",
        )

        assert nation.leader_name == "Ivan Grozny"
        assert nation.leader_title == "Supreme Ruler"
        assert nation.history_url == "https://vk.com/@goliath-history"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value,error",
        [
            ("leader_name", "x", LeaderNameInvalidError),
            ("leader_name", "Ivan\nGrozny", LeaderNameInvalidError),
            ("leader_title", "", LeaderTitleInvalidError),
            ("leader_title", "Boss​Boss", LeaderTitleInvalidError),
            ("history_url", "http://vk.com/@x", HistoryUrlInvalidError),
            ("history_url", "https://evil.com/@x", HistoryUrlInvalidError),
        ],
    )
    async def test_create_invalid_profile_persists_nothing(
        self, test_db_session, config, field, value, error
    ):
        """A rejected profile field leaves no nation row and frees no
        province (INV-3 atomicity)."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])

        profile = dict(VALID_PROFILE)
        profile[field] = value
        with pytest.raises(error):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Test Nation",
                color_hex="#FF0000",
                province_ids=[1],
                config=config,
                **profile,
            )

        assert await self._nation_count(test_db_session) == 0
        assert await self._province_is_free(test_db_session, 1)

    @pytest.mark.asyncio
    async def test_create_inv1_before_profile_errors(
        self, test_db_session, config
    ):
        """Spec Part 2 order: NATION_ALREADY_EXISTS wins over profile errors."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1, 2])
        await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="First Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )

        with pytest.raises(NationAlreadyExistsError):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Second Nation",
                color_hex="#00FF00",
                province_ids=[2],
                config=config,
                leader_name="x",  # would fail on its own
                leader_title="x",
                history_url="not-a-url",
            )

    @pytest.mark.asyncio
    async def test_create_profile_error_before_name_taken(
        self, test_db_session, config
    ):
        """Spec Part 2 order: profile errors are reported before INV-2."""
        owner = await self._create_player(test_db_session, vk_user_id=11111)
        player = await self._create_player(test_db_session, vk_user_id=22222)
        await self._create_provinces(test_db_session, [1, 2])
        await NationService.create(
            test_db_session,
            owner_player_id=owner.id,
            name="Taken Name",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )

        with pytest.raises(LeaderNameInvalidError):
            await NationService.create(
                test_db_session,
                owner_player_id=player.id,
                name="Taken Name",  # also taken — but profile fails first
                color_hex="#FF0000",
                province_ids=[2],
                config=config,
                leader_name="x",
                leader_title=VALID_PROFILE["leader_title"],
                history_url=VALID_PROFILE["history_url"],
            )

    @pytest.mark.asyncio
    async def test_update_partial_profile_fields(self, test_db_session, config):
        """Only provided fields change; None leaves the rest untouched."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )

        updated = await NationService.update(
            test_db_session,
            nation_id=nation.id,
            leader_title="Grand Duke",
            config=config,
        )

        assert updated.leader_title == "Grand Duke"
        assert updated.leader_name == VALID_PROFILE["leader_name"]
        assert updated.history_url == VALID_PROFILE["history_url"]
        assert updated.name == "Test Nation"
        assert updated.color_hex == "#FF0000"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value,error",
        [
            ("leader_name", "   ", LeaderNameInvalidError),
            ("leader_title", "  ", LeaderTitleInvalidError),
            ("history_url", " ", HistoryUrlInvalidError),
        ],
    )
    async def test_update_empty_string_is_error_not_clear(
        self, test_db_session, config, field, value, error
    ):
        """INV-8: a whitespace-only value is invalid, never a clear."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )

        with pytest.raises(error):
            await NationService.update(
                test_db_session,
                nation_id=nation.id,
                config=config,
                **{field: value},
            )

        await test_db_session.refresh(nation)
        assert getattr(nation, field) == VALID_PROFILE[field]

    @pytest.mark.asyncio
    async def test_update_invalid_profile_changes_nothing(
        self, test_db_session, config
    ):
        """An invalid profile field aborts the whole update — even a
        valid name in the same call is not applied."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Old Name",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )

        with pytest.raises(HistoryUrlInvalidError):
            await NationService.update(
                test_db_session,
                nation_id=nation.id,
                name="New Name",
                history_url="https://evil.com/@x",
                config=config,
            )

        await test_db_session.refresh(nation)
        assert nation.name == "Old Name"
        assert nation.history_url == VALID_PROFILE["history_url"]

    @pytest.mark.asyncio
    async def test_legacy_nation_rename_and_partial_profile_fill(
        self, test_db_session, config
    ):
        """A NULL-profile legacy nation still accepts a rename/recolor,
        and its profile can be filled field by field."""
        player = await self._create_player(test_db_session)
        await self._create_provinces(test_db_session, [1])
        legacy = Nation(
            owner_player_id=player.id,
            name="Legacy Nation",
            color_hex="#123456",
            created_at=datetime.now(timezone.utc),
        )
        test_db_session.add(legacy)
        await test_db_session.flush()

        # Plain rename works without touching the profile.
        renamed = await NationService.update(
            test_db_session,
            nation_id=legacy.id,
            name="Renamed Legacy",
            config=config,
        )
        assert renamed.name == "Renamed Legacy"
        assert renamed.leader_name is None
        assert renamed.leader_title is None
        assert renamed.history_url is None

        # Profile fields can then be filled one call at a time.
        step1 = await NationService.update(
            test_db_session,
            nation_id=legacy.id,
            leader_name=VALID_PROFILE["leader_name"],
            config=config,
        )
        assert step1.leader_name == VALID_PROFILE["leader_name"]
        assert step1.leader_title is None
        assert step1.history_url is None

        step2 = await NationService.update(
            test_db_session,
            nation_id=legacy.id,
            leader_title=VALID_PROFILE["leader_title"],
            history_url=VALID_PROFILE["history_url"],
            config=config,
        )
        assert step2.leader_title == VALID_PROFILE["leader_title"]
        assert step2.history_url == VALID_PROFILE["history_url"]


class TestScheduledActionService:
    """Tests for ScheduledActionService."""

    async def _create_nation(self, session) -> Nation:
        """Helper to create a nation with player and provinces."""
        player = Player(vk_user_id=11111)
        session.add(player)
        await session.flush()

        provinces = [Province(id=pid, nation_id=None) for pid in [1, 2]]
        for p in provinces:
            session.add(p)
        await session.flush()

        config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        nation = await NationService.create(
            session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
            **VALID_PROFILE,
        )
        return nation
    
    @pytest.mark.asyncio
    async def test_submit_action_once_per_turn(self, test_db_session):
        """Test ONCE_PER_TURN frequency rule."""
        nation = await self._create_nation(test_db_session)
        
        # First action should succeed
        action1 = await ScheduledActionService.submit(
            test_db_session,
            nation_id=nation.id,
            module_slug="test_module",
            action_type="test_action",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_TURN,
        )
        assert action1.status == ScheduledActionStatus.PENDING
        
        # Second action on same turn should fail
        with pytest.raises(FrequencyCapExceededError):
            await ScheduledActionService.submit(
                test_db_session,
                nation_id=nation.id,
                module_slug="test_module",
                action_type="test_action",
                payload={"data": "value2"},
                turn_number=1,
                frequency_rule=FrequencyRule.ONCE_PER_TURN,
            )
    
    @pytest.mark.asyncio
    async def test_submit_action_once_per_game(self, test_db_session):
        """Test ONCE_PER_GAME frequency rule."""
        nation = await self._create_nation(test_db_session)
        
        # First action should succeed
        action1 = await ScheduledActionService.submit(
            test_db_session,
            nation_id=nation.id,
            module_slug="test_module",
            action_type="test_action",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_GAME,
        )
        assert action1.status == ScheduledActionStatus.PENDING
        
        # Second action on different turn should still fail
        with pytest.raises(FrequencyCapExceededError):
            await ScheduledActionService.submit(
                test_db_session,
                nation_id=nation.id,
                module_slug="test_module",
                action_type="test_action",
                payload={"data": "value2"},
                turn_number=2,
                frequency_rule=FrequencyRule.ONCE_PER_GAME,
            )
    
    @pytest.mark.asyncio
    async def test_submit_action_multiple_per_turn(self, test_db_session):
        """Test MULTIPLE_PER_TURN frequency rule."""
        nation = await self._create_nation(test_db_session)
        
        # Submit up to cap
        for i in range(3):
            action = await ScheduledActionService.submit(
                test_db_session,
                nation_id=nation.id,
                module_slug="test_module",
                action_type="test_action",
                payload={"data": f"value{i}"},
                turn_number=1,
                frequency_rule=FrequencyRule.MULTIPLE_PER_TURN,
                frequency_cap=3,
            )
            assert action.status == ScheduledActionStatus.PENDING
        
        # Fourth action should fail
        with pytest.raises(FrequencyCapExceededError):
            await ScheduledActionService.submit(
                test_db_session,
                nation_id=nation.id,
                module_slug="test_module",
                action_type="test_action",
                payload={"data": "value4"},
                turn_number=1,
                frequency_rule=FrequencyRule.MULTIPLE_PER_TURN,
                frequency_cap=3,
            )
    
    @pytest.mark.asyncio
    async def test_submit_action_unlimited(self, test_db_session):
        """Test UNLIMITED frequency rule."""
        nation = await self._create_nation(test_db_session)
        
        # Should be able to submit many actions
        for i in range(10):
            action = await ScheduledActionService.submit(
                test_db_session,
                nation_id=nation.id,
                module_slug="test_module",
                action_type="test_action",
                payload={"data": f"value{i}"},
                turn_number=1,
                frequency_rule=FrequencyRule.UNLIMITED,
            )
            assert action.status == ScheduledActionStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_submit_action_different_types_separate_limits(self, test_db_session):
        """Test that different action types have separate frequency limits."""
        nation = await self._create_nation(test_db_session)
        
        # Submit action of type A
        await ScheduledActionService.submit(
            test_db_session,
            nation_id=nation.id,
            module_slug="test_module",
            action_type="action_a",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_TURN,
        )
        
        # Should be able to submit action of type B on same turn
        action = await ScheduledActionService.submit(
            test_db_session,
            nation_id=nation.id,
            module_slug="test_module",
            action_type="action_b",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_TURN,
        )
        assert action.status == ScheduledActionStatus.PENDING
