"""
Domain services for module 00_core.

Provides business logic for Player, Nation, and ScheduledAction entities.
Enforces all invariants defined in the system specification.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ColorTakenError,
    FrequencyCapExceededError,
    NameTakenError,
    NationAlreadyExistsError,
    NationNotFoundError,
    ProvinceCountOutOfRangeError,
    ProvinceNotFoundError,
    ProvinceTakenError,
)
from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    ScheduledActionStatus,
)

if TYPE_CHECKING:
    from typing import Self


class FrequencyRule(str):
    """Frequency rules for scheduled actions."""
    
    ONCE_PER_TURN = "ONCE_PER_TURN"
    ONCE_PER_GAME = "ONCE_PER_GAME"
    MULTIPLE_PER_TURN = "MULTIPLE_PER_TURN"
    UNLIMITED = "UNLIMITED"


class PlayerService:
    """Service for Player entity operations."""
    
    @staticmethod
    async def get_or_create(session: AsyncSession, vk_user_id: int) -> Player:
        """
        Get an existing player by vk_user_id, or create a new one.
        
        Args:
            session: The async database session.
            vk_user_id: The VK user ID.
            
        Returns:
            The existing or newly created Player instance.
        """
        result = await session.execute(
            select(Player).where(Player.vk_user_id == vk_user_id)
        )
        player = result.scalar_one_or_none()
        
        if player is None:
            player = Player(
                id=str(uuid.uuid4()),
                vk_user_id=vk_user_id,
                created_at=datetime.now(timezone.utc),
            )
            session.add(player)
            await session.flush()
        
        return player


class NationService:
    """Service for Nation entity operations."""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        owner_player_id: str,
        name: str,
        color_hex: str,
        province_ids: list[int],
        config: CoreConfig,
    ) -> Nation:
        """
        Create a new nation with the given provinces.
        
        Enforces INV-1 (one nation per player), INV-2 (unique name/color),
        INV-3 (atomic province assignment), and province count constraints.
        
        Args:
            session: The async database session.
            owner_player_id: The player ID who will own the nation.
            name: The nation name.
            color_hex: The nation color in hex format (#RRGGBB).
            province_ids: List of province IDs to assign to the nation.
            config: The core configuration for validation constraints.
            
        Returns:
            The newly created Nation instance.
            
        Raises:
            NationAlreadyExistsError: If the player already has a nation.
            NameTakenError: If the name is already taken.
            ColorTakenError: If the color is already taken.
            ProvinceNotFoundError: If any province ID does not exist.
            ProvinceTakenError: If any province is already owned.
            ProvinceCountOutOfRangeError: If province count violates constraints.
        """
        # INV-1: Check if player already has a nation
        result = await session.execute(
            select(Nation).where(Nation.owner_player_id == owner_player_id)
        )
        if result.scalar_one_or_none() is not None:
            raise NationAlreadyExistsError(owner_player_id)
        
        # INV-2: Check if name is already taken
        result = await session.execute(
            select(Nation).where(Nation.name == name)
        )
        if result.scalar_one_or_none() is not None:
            raise NameTakenError(name)
        
        # INV-2: Check if color is already taken
        result = await session.execute(
            select(Nation).where(Nation.color_hex == color_hex)
        )
        if result.scalar_one_or_none() is not None:
            raise ColorTakenError(color_hex)
        
        # Validate province count constraints
        province_count = len(province_ids)
        if (province_count < config.nation.min_provinces_per_nation or
            province_count > config.nation.max_provinces_per_nation):
            raise ProvinceCountOutOfRangeError(
                province_count,
                config.nation.min_provinces_per_nation,
                config.nation.max_provinces_per_nation,
            )
        
        # Fetch all provinces to validate they exist and are free
        result = await session.execute(
            select(Province).where(Province.id.in_(province_ids))
        )
        provinces = result.scalars().all()
        
        # Check for missing provinces
        found_ids = {p.id for p in provinces}
        missing_ids = set(province_ids) - found_ids
        if missing_ids:
            raise ProvinceNotFoundError(missing_ids.pop())
        
        # Check for already-owned provinces
        for province in provinces:
            if province.nation_id is not None:
                raise ProvinceTakenError(province.id)
        
        # INV-3: Atomic transaction - create nation and assign provinces
        nation = Nation(
            id=str(uuid.uuid4()),
            owner_player_id=owner_player_id,
            name=name,
            color_hex=color_hex,
            created_at=datetime.now(timezone.utc),
        )
        session.add(nation)
        await session.flush()  # Get the nation ID
        
        # Assign provinces
        for province in provinces:
            province.nation_id = nation.id
        
        return nation
    
    @staticmethod
    async def update(
        session: AsyncSession,
        nation_id: str,
        name: str | None = None,
        color_hex: str | None = None,
    ) -> Nation:
        """
        Update a nation's name and/or color.
        
        Enforces INV-2 (unique name/color).
        
        Args:
            session: The async database session.
            nation_id: The nation ID to update.
            name: Optional new name.
            color_hex: Optional new color.
            
        Returns:
            The updated Nation instance.
            
        Raises:
            NationNotFoundError: If the nation does not exist.
            NameTakenError: If the new name is already taken by another nation.
            ColorTakenError: If the new color is already taken by another nation.
        """
        result = await session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        nation = result.scalar_one_or_none()
        
        if nation is None:
            raise NationNotFoundError(nation_id)
        
        if name is not None and name != nation.name:
            # Check if name is already taken by another nation
            result = await session.execute(
                select(Nation).where(Nation.name == name, Nation.id != nation_id)
            )
            if result.scalar_one_or_none() is not None:
                raise NameTakenError(name)
            nation.name = name
        
        if color_hex is not None and color_hex != nation.color_hex:
            # Check if color is already taken by another nation
            result = await session.execute(
                select(Nation).where(Nation.color_hex == color_hex, Nation.id != nation_id)
            )
            if result.scalar_one_or_none() is not None:
                raise ColorTakenError(color_hex)
            nation.color_hex = color_hex
        
        return nation
    
    @staticmethod
    async def delete(session: AsyncSession, nation_id: str) -> None:
        """
        Delete a nation and free its provinces.
        
        Enforces INV-6: deletion frees provinces instead of deleting them.
        
        Args:
            session: The async database session.
            nation_id: The nation ID to delete.
            
        Raises:
            NationNotFoundError: If the nation does not exist.
        """
        result = await session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        nation = result.scalar_one_or_none()
        
        if nation is None:
            raise NationNotFoundError(nation_id)
        
        # INV-6: Free all provinces by setting nation_id to NULL
        for province in nation.provinces:
            province.nation_id = None
        
        # Delete the nation
        await session.delete(nation)


class ScheduledActionService:
    """Service for ScheduledAction entity operations."""
    
    @staticmethod
    async def submit(
        session: AsyncSession,
        nation_id: str,
        module_slug: str,
        action_type: str,
        payload: dict,
        turn_number: int,
        frequency_rule: str,
        frequency_cap: int | None = None,
    ) -> ScheduledAction:
        """
        Submit a scheduled action for execution.
        
        Enforces INV-FREQUENCY: validates action frequency based on the rule.
        
        Args:
            session: The async database session.
            nation_id: The nation ID submitting the action.
            module_slug: The module that owns this action.
            action_type: The type of action within the module.
            payload: The action payload (interpreted by the module).
            turn_number: The turn number this action is scheduled for.
            frequency_rule: The frequency rule (see FrequencyRule).
            frequency_cap: The cap for MULTIPLE_PER_TURN rule.
            
        Returns:
            The newly created ScheduledAction instance.
            
        Raises:
            FrequencyCapExceededError: If the frequency cap is exceeded.
        """
        # INV-FREQUENCY: Check frequency constraints
        max_allowed = None
        
        if frequency_rule == FrequencyRule.ONCE_PER_TURN:
            max_allowed = 1
            # Count actions for this nation, module, type, on this specific turn
            result = await session.execute(
                select(ScheduledAction).where(
                    ScheduledAction.nation_id == nation_id,
                    ScheduledAction.module_slug == module_slug,
                    ScheduledAction.action_type == action_type,
                    ScheduledAction.turn_number == turn_number,
                    ScheduledAction.status == ScheduledActionStatus.PENDING,
                )
            )
            current_count = len(result.scalars().all())
            
        elif frequency_rule == FrequencyRule.ONCE_PER_GAME:
            max_allowed = 1
            # Count actions for this nation, module, type, across all turns
            result = await session.execute(
                select(ScheduledAction).where(
                    ScheduledAction.nation_id == nation_id,
                    ScheduledAction.module_slug == module_slug,
                    ScheduledAction.action_type == action_type,
                    ScheduledAction.status == ScheduledActionStatus.PENDING,
                )
            )
            current_count = len(result.scalars().all())
            
        elif frequency_rule == FrequencyRule.MULTIPLE_PER_TURN:
            if frequency_cap is None:
                raise ValueError("frequency_cap is required for MULTIPLE_PER_TURN rule")
            max_allowed = frequency_cap
            # Count actions for this nation, module, type, on this specific turn
            result = await session.execute(
                select(ScheduledAction).where(
                    ScheduledAction.nation_id == nation_id,
                    ScheduledAction.module_slug == module_slug,
                    ScheduledAction.action_type == action_type,
                    ScheduledAction.turn_number == turn_number,
                    ScheduledAction.status == ScheduledActionStatus.PENDING,
                )
            )
            current_count = len(result.scalars().all())
            
        elif frequency_rule == FrequencyRule.UNLIMITED:
            # No constraint
            current_count = 0
            max_allowed = float("inf")
            
        else:
            raise ValueError(f"Unknown frequency rule: {frequency_rule}")
        
        # Check if cap is exceeded
        if current_count >= max_allowed:
            raise FrequencyCapExceededError(action_type, current_count, max_allowed)
        
        # Create the scheduled action
        action = ScheduledAction(
            id=str(uuid.uuid4()),
            nation_id=nation_id,
            module_slug=module_slug,
            action_type=action_type,
            payload=payload,
            turn_number=turn_number,
            status=ScheduledActionStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        session.add(action)
        await session.flush()
        
        return action

"""
Domain services for module 00_core.

Provides business logic for Player, Nation, and ScheduledAction entities.
Enforces all invariants defined in the system specification.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ColorTakenError,
    FrequencyCapExceededError,
    NameTakenError,
    NationAlreadyExistsError,
    NationNotFoundError,
    ProvinceCountOutOfRangeError,
    ProvinceNotFoundError,
    ProvinceTakenError,
)
from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    ScheduledActionStatus,
)

if TYPE_CHECKING:
    from typing import Self


class FrequencyRule(str):
    """Frequency rules for scheduled actions."""
    
    ONCE_PER_TURN = "ONCE_PER_TURN"
    ONCE_PER_GAME = "ONCE_PER_GAME"
    MULTIPLE_PER_TURN = "MULTIPLE_PER_TURN"
    UNLIMITED = "UNLIMITED"


class PlayerService:
    """Service for Player entity operations."""
    
    @staticmethod
    async def get_or_create(session: AsyncSession, vk_user_id: int) -> Player:
        """
        Get an existing player by vk_user_id, or create a new one.
        
        Args:
            session: The async database session.
            vk_user_id: The VK user ID.
            
        Returns:
            The existing or newly created Player instance.
        """
        result = await session.execute(
            select(Player).where(Player.vk_user_id == vk_user_id)
        )
        player = result.scalar_one_or_none()
        
        if player is None:
            player = Player(
                id=str(uuid.uuid4()),
                vk_user_id=vk_user_id,
                created_at=datetime.now(timezone.utc),
            )
            session.add(player)
            await session.flush()
        
        return player


class NationService:
    """Service for Nation entity operations."""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        owner_player_id: str,
        name: str,
        color_hex: str,
        province_ids: list[int],
        config: CoreConfig,
    ) -> Nation:
        """
        Create a new nation with the given provinces.
        
        Enforces INV-1 (one nation per player), INV-2 (unique name/color),
        INV-3 (atomic province assignment), and province count constraints.
        
        Args:
            session: The async database session.
            owner_player_id: The player ID who will own the nation.
            name: The nation name.
            color_hex: The nation color in hex format (#RRGGBB).
            province_ids: List of province IDs to assign to the nation.
            config: The core configuration for validation constraints.
            
        Returns:
            The newly created Nation instance.
            
        Raises:
            NationAlreadyExistsError: If the player already has a nation.
            NameTakenError: If the name is already taken.
            ColorTakenError: If the color is already taken.
            ProvinceNotFoundError: If any province ID does not exist.
            ProvinceTakenError: If any province is already owned.
            ProvinceCountOutOfRangeError: If province count violates constraints.
        """
        # INV-1: Check if player already has a nation
        result = await session.execute(
            select(Nation).where(Nation.owner_player_id == owner_player_id)
        )
        if result.scalar_one_or_none() is not None:
            raise NationAlreadyExistsError(owner_player_id)
        
        # INV-2: Check if name is already taken
        result = await session.execute(
            select(Nation).where(Nation.name == name)
        )
        if result.scalar_one_or_none() is not None:
            raise NameTakenError(name)
        
        # INV-2: Check if color is already taken
        result = await session.execute(
            select(Nation).where(Nation.color_hex == color_hex)
        )
        if result.scalar_one_or_none() is not None:
            raise ColorTakenError(color_hex)
        
        # Validate province count constraints
        province_count = len(province_ids)
        if (province_count < config.nation.min_provinces_per_nation or
            province_count > config.nation.max_provinces_per_nation):
            raise ProvinceCountOutOfRangeError(
                province_count,
                config.nation.min_provinces_per_nation,
                config.nation.max_provinces_per_nation,
            )
        
        # Fetch all provinces to validate they exist and are free
        result = await session.execute(
            select(Province).where(Province.id.in_(province_ids))
        )
        provinces = result.scalars().all()
        
        # Check for missing provinces
        found_ids = {p.id for p in provinces}
        missing_ids = set(province_ids) - found_ids
        if missing_ids:
            raise ProvinceNotFoundError(missing_ids.pop())
        
        # Check for already-owned provinces
        for province in provinces:
            if province.nation_id is not None:
                raise ProvinceTakenError(province.id)
        
        # INV-3: Atomic transaction - create nation and assign provinces
        nation = Nation(
            id=str(uuid.uuid4()),
            owner_player_id=owner_player_id,
            name=name,
            color_hex=color_hex,
            created_at=datetime.now(timezone.utc),
        )
        session.add(nation)
        await session.flush()  # Get the nation ID
        
        # Assign provinces
        for province in provinces:
            province.nation_id = nation.id
        
        return nation
    
    @staticmethod
    async def update(
        session: AsyncSession,
        nation_id: str,
        name: str | None = None,
        color_hex: str | None = None,
    ) -> Nation:
        """
        Update a nation's name and/or color.
        
        Enforces INV-2 (unique name/color).
        
        Args:
            session: The async database session.
            nation_id: The nation ID to update.
            name: Optional new name.
            color_hex: Optional new color.
            
        Returns:
            The updated Nation instance.
            
        Raises:
            NationNotFoundError: If the nation does not exist.
            NameTakenError: If the new name is already taken by another nation.
            ColorTakenError: If the new color is already taken by another nation.
        """
        result = await session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        nation = result.scalar_one_or_none()
        
        if nation is None:
            raise NationNotFoundError(nation_id)
        
        if name is not None and name != nation.name:
            # Check if name is already taken by another nation
            result = await session.execute(
                select(Nation).where(Nation.name == name, Nation.id != nation_id)
            )
            if result.scalar_one_or_none() is not None:
                raise NameTakenError(name)
            nation.name = name
        
        if color_hex is not None and color_hex != nation.color_hex:
            # Check if color is already taken by another nation
            result = await session.execute(
                select(Nation).where(Nation.color_hex == color_hex, Nation.id != nation_id)
            )
            if result.scalar_one_or_none() is not None:
                raise ColorTakenError(color_hex)
            nation.color_hex = color_hex
        
        return nation
    
    @staticmethod
    async def delete(session: AsyncSession, nation_id: str) -> None:
        """
        Delete a nation and free its provinces.
        
        Enforces INV-6: deletion frees provinces instead of deleting them.
        
        Args:
            session: The async database session.
            nation_id: The nation ID to delete.
            
        Raises:
            NationNotFoundError: If the nation does not exist.
        """
        result = await session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        nation = result.scalar_one_or_none()
        
        if nation is None:
            raise NationNotFoundError(nation_id)
        
        # INV-6: Free all provinces by setting nation_id to NULL
        # Use select to fetch provinces to avoid lazy loading in async context
        result = await session.execute(
            select(Province).where(Province.nation_id == nation_id)
        )
        provinces = result.scalars().all()
        for province in provinces:
            province.nation_id = None
        
        # Delete the nation
        await session.delete(nation)


class ScheduledActionService:
    """Service for ScheduledAction entity operations."""
    
    @staticmethod
    async def submit(
        session: AsyncSession,
        nation_id: str,
        module_slug: str,
        action_type: str,
        payload: dict,
        turn_number: int,
        frequency_rule: str,
        frequency_cap: int | None = None,
    ) -> ScheduledAction:
        """
        Submit a scheduled action for execution.
        
        Enforces INV-FREQUENCY: validates action frequency based on the rule.
        
        Args:
            session: The async database session.
            nation_id: The nation ID submitting the action.
            module_slug: The module that owns this action.
            action_type: The type of action within the module.
            payload: The action payload (interpreted by the module).
            turn_number: The turn number this action is scheduled for.
            frequency_rule: The frequency rule (see FrequencyRule).
            frequency_cap: The cap for MULTIPLE_PER_TURN rule.
            
        Returns:
            The newly created ScheduledAction instance.
            
        Raises:
            FrequencyCapExceededError: If the frequency cap is exceeded.
        """
        # INV-FREQUENCY: Check frequency constraints
        max_allowed = None
        
        if frequency_rule == FrequencyRule.ONCE_PER_TURN:
            max_allowed = 1
            # Count actions for this nation, module, type, on this specific turn
            result = await session.execute(
                select(ScheduledAction).where(
                    ScheduledAction.nation_id == nation_id,
                    ScheduledAction.module_slug == module_slug,
                    ScheduledAction.action_type == action_type,
                    ScheduledAction.turn_number == turn_number,
                    ScheduledAction.status == ScheduledActionStatus.PENDING,
                )
            )
            current_count = len(result.scalars().all())
            
        elif frequency_rule == FrequencyRule.ONCE_PER_GAME:
            max_allowed = 1
            # Count actions for this nation, module, type, across all turns
            result = await session.execute(
                select(ScheduledAction).where(
                    ScheduledAction.nation_id == nation_id,
                    ScheduledAction.module_slug == module_slug,
                    ScheduledAction.action_type == action_type,
                    ScheduledAction.status == ScheduledActionStatus.PENDING,
                )
            )
            current_count = len(result.scalars().all())
            
        elif frequency_rule == FrequencyRule.MULTIPLE_PER_TURN:
            if frequency_cap is None:
                raise ValueError("frequency_cap is required for MULTIPLE_PER_TURN rule")
            max_allowed = frequency_cap
            # Count actions for this nation, module, type, on this specific turn
            result = await session.execute(
                select(ScheduledAction).where(
                    ScheduledAction.nation_id == nation_id,
                    ScheduledAction.module_slug == module_slug,
                    ScheduledAction.action_type == action_type,
                    ScheduledAction.turn_number == turn_number,
                    ScheduledAction.status == ScheduledActionStatus.PENDING,
                )
            )
            current_count = len(result.scalars().all())
            
        elif frequency_rule == FrequencyRule.UNLIMITED:
            # No constraint
            current_count = 0
            max_allowed = float("inf")
            
        else:
            raise ValueError(f"Unknown frequency rule: {frequency_rule}")
        
        # Check if cap is exceeded
        if current_count >= max_allowed:
            raise FrequencyCapExceededError(action_type, current_count, max_allowed)
        
        # Create the scheduled action
        action = ScheduledAction(
            id=str(uuid.uuid4()),
            nation_id=nation_id,
            module_slug=module_slug,
            action_type=action_type,
            payload=payload,
            turn_number=turn_number,
            status=ScheduledActionStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        session.add(action)
        await session.flush()
        
        return action
