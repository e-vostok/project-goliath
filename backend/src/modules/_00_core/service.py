"""
Domain services for module 00_core.

Provides business logic for Player, Nation, and ScheduledAction entities.
Enforces all invariants defined in the system specification.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Sequence

from sqlalchemy import insert, select
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
from modules._00_core.profile_rules import (
    validate_history_url,
    validate_leader_name,
    validate_leader_title,
)

if TYPE_CHECKING:
    from typing import Self


class FrequencyRule(str):
    """Frequency rules for scheduled actions."""

    ONCE_PER_TURN = "ONCE_PER_TURN"
    ONCE_PER_GAME = "ONCE_PER_GAME"
    MULTIPLE_PER_TURN = "MULTIPLE_PER_TURN"
    UNLIMITED = "UNLIMITED"


ProvinceKind = Literal["LAND", "SEA"]


@dataclass(frozen=True)
class NodeSpec:
    """One map node from manifest.json: an id and its kind."""

    id: int
    kind: ProvinceKind


@dataclass(frozen=True)
class EnsureNodesResult:
    """Outcome of ProvinceService.ensure_nodes (all lists sorted)."""

    added: list[int] = field(default_factory=list)
    kind_mismatch: list[int] = field(default_factory=list)
    extra_in_db: list[int] = field(default_factory=list)


class ProvinceService:
    """Service for the provinces table (map nodes)."""

    @staticmethod
    async def ensure_nodes(
        session: AsyncSession,
        nodes: Sequence[NodeSpec],
    ) -> EnsureNodesResult:
        """
        Insert missing provinces for the given map nodes (INV-M5 helper).

        Only inserts rows that do not exist yet (nation_id NULL); never
        updates or deletes. Idempotent: a second call adds nothing. Runs
        inside the caller's transaction — this method never commits.

        Args:
            session: The async database session.
            nodes: Node specs (id + kind) from manifest.json.

        Returns:
            EnsureNodesResult with the ids that were inserted, the ids
            whose existing row has a different kind (left unchanged), and
            ids present in the DB but absent from `nodes` (not removed) —
            the caller decides whether extra rows are fatal (INV-M5).

        Raises:
            ValueError: On duplicate ids or an invalid kind in `nodes`;
                nothing is written in that case.
        """
        ids = [node.id for node in nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate node ids in input")
        invalid_kinds = {node.kind for node in nodes} - {"LAND", "SEA"}
        if invalid_kinds:
            raise ValueError(
                f"Invalid node kinds in input: {sorted(invalid_kinds)}"
            )

        result = await session.execute(select(Province.id, Province.kind))
        existing = {row.id: row.kind for row in result.all()}

        spec_by_id = {node.id: node.kind for node in nodes}
        added = sorted(set(spec_by_id) - set(existing))
        kind_mismatch = sorted(
            node_id
            for node_id in set(spec_by_id) & set(existing)
            if existing[node_id] != spec_by_id[node_id]
        )
        extra_in_db = sorted(set(existing) - set(spec_by_id))

        if added:
            await session.execute(
                insert(Province),
                [
                    {"id": node_id, "kind": spec_by_id[node_id]}
                    for node_id in added
                ],
            )

        return EnsureNodesResult(
            added=added,
            kind_mismatch=kind_mismatch,
            extra_in_db=extra_in_db,
        )


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
        leader_name: str,
        leader_title: str,
        history_url: str,
    ) -> Nation:
        """
        Create a new nation with the given provinces and profile fields.

        Enforces INV-1 (one nation per player), INV-7 (mandatory profile
        fields), INV-2 (unique name/color), INV-3 (atomic province
        assignment), and province count constraints — in exactly the
        Spec Part 2 order: INV-1 -> profile fields (leader_name,
        leader_title, history_url) -> INV-2 -> province count ->
        province existence/freedom. Any failure persists nothing.

        Args:
            session: The async database session.
            owner_player_id: The player ID who will own the nation.
            name: The nation name.
            color_hex: The nation color in hex format (#RRGGBB).
            province_ids: List of province IDs to assign to the nation.
            config: The core configuration for validation constraints.
            leader_name: The leader's name (normalized and validated).
            leader_title: The leader's title (normalized and validated).
            history_url: Link to the nation's history article.

        Returns:
            The newly created Nation instance.

        Raises:
            NationAlreadyExistsError: If the player already has a nation.
            LeaderNameInvalidError: If the leader name fails Part 3 checks.
            LeaderTitleInvalidError: If the leader title fails Part 3 checks.
            HistoryUrlInvalidError: If the history URL fails Part 3 checks.
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

        # INV-7: profile fields are mandatory and validated before INV-2
        # (Spec Part 2 check order). The normalized values get stored.
        leader_name = validate_leader_name(leader_name, config)
        leader_title = validate_leader_title(leader_title, config)
        history_url = validate_history_url(history_url, config)

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
            leader_name=leader_name,
            leader_title=leader_title,
            history_url=history_url,
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
        leader_name: str | None = None,
        leader_title: str | None = None,
        history_url: str | None = None,
        *,
        config: CoreConfig,
    ) -> Nation:
        """
        Update a nation's name, color, and/or profile fields.

        Enforces INV-2 (unique name/color) and INV-8: a None argument
        leaves the field unchanged, while a provided value is normalized
        and validated up front — so a rejected field aborts the whole
        update before anything is mutated. Profile fields are required
        and can never be cleared; an empty (post-strip) string is a
        validation error, not a reset. Legacy nations with NULL profile
        fields still accept a plain rename/recolor.

        Args:
            session: The async database session.
            nation_id: The nation ID to update.
            name: Optional new name.
            color_hex: Optional new color.
            leader_name: Optional new leader name.
            leader_title: Optional new leader title.
            history_url: Optional new history URL.
            config: The core configuration for validation constraints.

        Returns:
            The updated Nation instance.

        Raises:
            NationNotFoundError: If the nation does not exist.
            LeaderNameInvalidError: If the leader name fails Part 3 checks.
            LeaderTitleInvalidError: If the leader title fails Part 3 checks.
            HistoryUrlInvalidError: If the history URL fails Part 3 checks.
            NameTakenError: If the new name is already taken by another nation.
            ColorTakenError: If the new color is already taken by another nation.
        """
        result = await session.execute(
            select(Nation).where(Nation.id == nation_id)
        )
        nation = result.scalar_one_or_none()

        if nation is None:
            raise NationNotFoundError(nation_id)

        # INV-8: validate every provided profile field before any
        # mutation, so a bad field leaves the whole update untouched.
        new_leader_name = (
            None if leader_name is None
            else validate_leader_name(leader_name, config)
        )
        new_leader_title = (
            None if leader_title is None
            else validate_leader_title(leader_title, config)
        )
        new_history_url = (
            None if history_url is None
            else validate_history_url(history_url, config)
        )

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

        if new_leader_name is not None:
            nation.leader_name = new_leader_name
        if new_leader_title is not None:
            nation.leader_title = new_leader_title
        if new_history_url is not None:
            nation.history_url = new_history_url

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
        
        # Orphan scheduled actions the same way: explicit nulling, not
        # FK cascade, so SQLite (foreign_keys pragma off) behaves
        # identically to PostgreSQL ON DELETE SET NULL.
        result = await session.execute(
            select(ScheduledAction).where(ScheduledAction.nation_id == nation_id)
        )
        for action in result.scalars().all():
            action.nation_id = None
        
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
