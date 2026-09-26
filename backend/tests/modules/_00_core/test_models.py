"""
Tests for 00_core ORM models.

Verifies model constraints, relationships, and invariants without mocking.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from modules._00_core.models import GameClock, Nation, Player, Province, ScheduledAction
from tests.fixtures.factories import PlayerFactory


@pytest.mark.asyncio
async def test_create_player_happy_path(test_db_session):
    """Test creating a player successfully."""
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=9999999999,
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(player)
    await test_db_session.flush()
    
    result = await test_db_session.execute(select(Player).where(Player.vk_user_id == 9999999999))
    retrieved_player = result.scalar_one()
    
    assert retrieved_player.id == player.id
    assert retrieved_player.vk_user_id == 9999999999
    assert retrieved_player.created_at is not None


@pytest.mark.asyncio
async def test_duplicate_vk_user_id_constraint(test_db_session):
    """Test that duplicate vk_user_id raises IntegrityError (INV-2)."""
    player1 = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,
        created_at=datetime.now(timezone.utc)
    )
    player2 = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,  # Same vk_user_id
        created_at=datetime.now(timezone.utc)
    )
    
    test_db_session.add(player1)
    await test_db_session.flush()
    
    test_db_session.add(player2)
    with pytest.raises(IntegrityError):
        await test_db_session.flush()


@pytest.mark.asyncio
async def test_create_nation_happy_path(test_db_session):
    """Test creating a nation successfully."""
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(player)
    await test_db_session.flush()
    
    nation = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player.id,
        name="Test Nation",
        color_hex="#00FF00",
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(nation)
    await test_db_session.flush()
    
    result = await test_db_session.execute(select(Nation).where(Nation.id == nation.id))
    retrieved_nation = result.scalar_one()
    
    assert retrieved_nation.id == nation.id
    assert retrieved_nation.owner_player_id == player.id
    assert retrieved_nation.name == "Test Nation"
    assert retrieved_nation.color_hex == "#00FF00"


@pytest.mark.asyncio
async def test_duplicate_owner_player_id_constraint(test_db_session):
    """Test that duplicate owner_player_id raises IntegrityError (INV-1)."""
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(player)
    await test_db_session.flush()
    
    nation1 = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player.id,
        name="Nation 1",
        color_hex="#111111",
        created_at=datetime.now(timezone.utc)
    )
    nation2 = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player.id,
        name="Nation 2",
        color_hex="#222222",
        created_at=datetime.now(timezone.utc)
    )
    
    test_db_session.add(nation1)
    await test_db_session.flush()
    
    test_db_session.add(nation2)
    with pytest.raises(IntegrityError):
        await test_db_session.flush()


@pytest.mark.asyncio
async def test_duplicate_nation_name_constraint(test_db_session):
    """Test that duplicate nation name raises IntegrityError (INV-2)."""
    player1 = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,
        created_at=datetime.now(timezone.utc)
    )
    player2 = Player(
        id=str(uuid.uuid4()),
        vk_user_id=2222222222,
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(player1)
    test_db_session.add(player2)
    await test_db_session.flush()
    
    nation1 = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player1.id,
        name="Duplicate Name",
        color_hex="#111111",
        created_at=datetime.now(timezone.utc)
    )
    nation2 = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player2.id,
        name="Duplicate Name",
        color_hex="#222222",
        created_at=datetime.now(timezone.utc)
    )
    
    test_db_session.add(nation1)
    await test_db_session.flush()
    
    test_db_session.add(nation2)
    with pytest.raises(IntegrityError):
        await test_db_session.flush()


@pytest.mark.asyncio
async def test_duplicate_nation_color_hex_constraint(test_db_session):
    """Test that duplicate color_hex raises IntegrityError (INV-2)."""
    player1 = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,
        created_at=datetime.now(timezone.utc)
    )
    player2 = Player(
        id=str(uuid.uuid4()),
        vk_user_id=2222222222,
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(player1)
    test_db_session.add(player2)
    await test_db_session.flush()
    
    nation1 = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player1.id,
        name="Nation 1",
        color_hex="#ABCDEF",
        created_at=datetime.now(timezone.utc)
    )
    nation2 = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player2.id,
        name="Nation 2",
        color_hex="#ABCDEF",
        created_at=datetime.now(timezone.utc)
    )
    
    test_db_session.add(nation1)
    await test_db_session.flush()
    
    test_db_session.add(nation2)
    with pytest.raises(IntegrityError):
        await test_db_session.flush()


@pytest.mark.asyncio
async def test_create_scheduled_action_happy_path(test_db_session):
    """Test creating a scheduled action successfully."""
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(player)
    await test_db_session.flush()
    
    nation = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player.id,
        name="Test Nation",
        color_hex="#FF0000",
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(nation)
    await test_db_session.flush()
    
    action = ScheduledAction(
        id=str(uuid.uuid4()),
        nation_id=nation.id,
        module_slug="test_module",
        action_type="test_action",
        payload={"test": "data"},
        turn_number=1,
        status="PENDING",
        created_at=datetime.now(timezone.utc),
    )
    test_db_session.add(action)
    await test_db_session.flush()
    
    result = await test_db_session.execute(
        select(ScheduledAction).where(ScheduledAction.id == action.id)
    )
    retrieved_action = result.scalar_one()
    
    assert retrieved_action.id == action.id
    assert retrieved_action.nation_id == nation.id
    assert retrieved_action.module_slug == "test_module"
    assert retrieved_action.action_type == "test_action"
    assert retrieved_action.payload == {"test": "data"}
    assert retrieved_action.turn_number == 1
    assert retrieved_action.status == "PENDING"


@pytest.mark.asyncio
async def test_game_clock_singleton_constraint(test_db_session):
    """Test that only one game_clock row can exist (singleton pattern)."""
    clock1 = GameClock(id=1, current_turn=0, next_tick_at=datetime.now(timezone.utc))
    test_db_session.add(clock1)
    await test_db_session.flush()
    
    # Try to insert a second row with id=1 (PK violation)
    clock2 = GameClock(id=1, current_turn=1, next_tick_at=datetime.now(timezone.utc))
    test_db_session.add(clock2)
    with pytest.raises(IntegrityError):
        await test_db_session.flush()
    
    # After error, need to rollback to continue
    await test_db_session.rollback()
    await test_db_session.begin()
    
    # Try to insert a second row with different id (CHECK constraint violation)
    clock3 = GameClock(id=2, current_turn=0, next_tick_at=datetime.now(timezone.utc))
    test_db_session.add(clock3)
    with pytest.raises(IntegrityError):
        await test_db_session.flush()


@pytest.mark.asyncio
async def test_province_nation_id_nullable(test_db_session):
    """Test that province nation_id can be NULL (free province)."""
    province = Province(id=1, nation_id=None)
    test_db_session.add(province)
    await test_db_session.flush()
    
    result = await test_db_session.execute(select(Province).where(Province.id == 1))
    retrieved_province = result.scalar_one()
    
    assert retrieved_province.id == 1
    assert retrieved_province.nation_id is None


@pytest.mark.asyncio
async def test_province_assignment(test_db_session):
    """Test assigning a province to a nation."""
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=1111111111,
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(player)
    await test_db_session.flush()
    
    nation = Nation(
        id=str(uuid.uuid4()),
        owner_player_id=player.id,
        name="Test Nation",
        color_hex="#FF0000",
        created_at=datetime.now(timezone.utc)
    )
    province = Province(id=1, nation_id=None)
    
    test_db_session.add(nation)
    test_db_session.add(province)
    await test_db_session.flush()
    
    # Assign province to nation
    province.nation_id = nation.id
    await test_db_session.flush()
    
    result = await test_db_session.execute(select(Province).where(Province.id == 1))
    retrieved_province = result.scalar_one()
    
    assert retrieved_province.nation_id == nation.id
