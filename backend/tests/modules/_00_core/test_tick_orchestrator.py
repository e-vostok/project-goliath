"""
Tests for the TickOrchestrator.

Tests the tick orchestration system including atomicity, error handling,
and proper tick_log persistence across rollbacks.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from core.tick.orchestrator import TickOrchestrator, TickPhase
from modules._00_core.models import GameClock, ScheduledAction, ScheduledActionStatus, TickLog, TickLogStatus
from modules._00_core.service import ScheduledActionService
from modules._00_core.tick_handler import finalize_tick, register_tick_handlers
from tests.fixtures.factories import GameClockFactory, NationFactory, PlayerFactory, ProvinceFactory


class TestTickOrchestrator:
    """Tests for TickOrchestrator."""
    
    @pytest.fixture(autouse=True)
    async def setup(self):
        """Setup and teardown for each test."""
        # Clear handlers before each test
        TickOrchestrator.clear_handlers()
        # Register the finalize callback
        register_tick_handlers()
        yield
        # Clear handlers after each test
        TickOrchestrator.clear_handlers()
    
    @pytest.fixture
    async def game_clock(self, test_db_session):
        """Create and return a game clock."""
        clock = GameClockFactory.build()
        test_db_session.add(clock)
        await test_db_session.flush()
        return clock
    
    @pytest.fixture
    async def sample_nation(self, test_db_session):
        """Create a sample nation with player and provinces."""
        from modules._00_core.config_schema import CoreConfig
        from modules._00_core.service import NationService
        
        player = PlayerFactory.build(vk_user_id=11111)
        test_db_session.add(player)
        await test_db_session.flush()
        
        provinces = [
            ProvinceFactory.build(id=1),
            ProvinceFactory.build(id=2),
        ]
        for p in provinces:
            test_db_session.add(p)
        await test_db_session.flush()
        
        config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        nation = await NationService.create(
            test_db_session,
            owner_player_id=player.id,
            name="Test Nation",
            color_hex="#FF0000",
            province_ids=[1],
            config=config,
        )
        return nation
    
    @pytest.mark.asyncio
    async def test_run_tick_no_handlers(self, test_db_session, game_clock):
        """Test that run_tick with no handlers completes and increments current_turn."""
        initial_turn = game_clock.current_turn
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Refresh the clock
        await test_db_session.refresh(game_clock)
        
        # Verify turn was incremented
        assert game_clock.current_turn == initial_turn + 1
        assert game_clock.last_tick_at is not None
        assert game_clock.next_tick_at is not None
        
        # Verify tick log was created with COMPLETED status
        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.COMPLETED
        assert tick_log.finished_at is not None
        assert tick_log.error_message is None
    
    @pytest.mark.asyncio
    async def test_run_tick_with_handler(self, test_db_session, game_clock):
        """Test that run_tick executes registered handlers."""
        executed_phases = []
        
        async def dummy_handler(session, turn_number):
            executed_phases.append(turn_number)
        
        # Register a handler
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, dummy_handler)
        
        initial_turn = game_clock.current_turn
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Verify handler was executed
        assert len(executed_phases) == 1
        assert executed_phases[0] == initial_turn + 1
        
        # Verify turn was incremented
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn + 1
    
    @pytest.mark.asyncio
    async def test_run_tick_handler_raises_rollback(self, test_db_session, game_clock, sample_nation):
        """Test that handler exception causes rollback and tick_log records failure."""
        # Create a scheduled action to verify it stays PENDING after rollback
        from modules._00_core.service import FrequencyRule
        action = await ScheduledActionService.submit(
            test_db_session,
            nation_id=sample_nation.id,
            module_slug="test_module",
            action_type="test_action",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_TURN,
        )
        action_id = action.id
        
        initial_turn = game_clock.current_turn
        
        # Register a handler that raises
        async def failing_handler(session, turn_number):
            raise ValueError("Simulated handler failure")
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)
        
        # Run tick - should raise
        with pytest.raises(ValueError, match="Simulated handler failure"):
            await TickOrchestrator.run_tick(test_db_session)
        
        # Verify ROLLBACK: current_turn unchanged
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn
        
        # Verify ROLLBACK: action still PENDING (not applied)
        result = await test_db_session.execute(
            select(ScheduledAction).where(ScheduledAction.id == action_id)
        )
        action = result.scalar_one()
        assert action.status == ScheduledActionStatus.PENDING
        
        # Verify tick_log survives rollback with FAILED status
        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.FAILED
        assert tick_log.finished_at is not None
        assert "Simulated handler failure" in tick_log.error_message
    
    @pytest.mark.asyncio
    async def test_run_tick_multiple_phases_order(self, test_db_session, game_clock):
        """Test that handlers execute in phase order."""
        execution_order = []
        
        async def handler_phase1(session, turn_number):
            execution_order.append("PHASE_1")
        
        async def handler_phase2(session, turn_number):
            execution_order.append("PHASE_2")
        
        async def handler_phase3(session, turn_number):
            execution_order.append("PHASE_3")
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, handler_phase1)
        TickOrchestrator.register(TickPhase.PHASE_2_PRODUCTION, handler_phase2)
        TickOrchestrator.register(TickPhase.PHASE_3_CONSUMPTION, handler_phase3)
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Verify execution order
        assert execution_order == ["PHASE_1", "PHASE_2", "PHASE_3"]
    
    @pytest.mark.asyncio
    async def test_run_tick_multiple_handlers_same_phase(self, test_db_session, game_clock):
        """Test that multiple handlers in the same phase all execute."""
        execution_count = [0]
        
        async def handler1(session, turn_number):
            execution_count[0] += 1
        
        async def handler2(session, turn_number):
            execution_count[0] += 1
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, handler1)
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, handler2)
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Verify both handlers executed
        assert execution_count[0] == 2
    
    @pytest.mark.asyncio
    async def test_run_tick_all_phases_empty(self, test_db_session, game_clock):
        """Test that all phases are iterated even with no handlers."""
        initial_turn = game_clock.current_turn
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Should complete successfully
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn + 1
    
    @pytest.mark.asyncio
    async def test_finalize_tick_updates_clock(self, test_db_session, game_clock):
        """Test that finalize_tick correctly updates the game clock."""
        initial_turn = game_clock.current_turn
        next_turn = initial_turn + 1
        
        await finalize_tick(test_db_session, next_turn)
        
        await test_db_session.refresh(game_clock)
        
        assert game_clock.current_turn == next_turn
        assert game_clock.last_tick_at is not None
        assert game_clock.next_tick_at is not None
    
    @pytest.mark.asyncio
    async def test_tick_log_persistence_separate_session(self, test_db_session, game_clock):
        """Test that tick_log is written in a separate session from the tick transaction."""
        initial_turn = game_clock.current_turn
        
        # Register a handler that will fail
        async def failing_handler(session, turn_number):
            raise ValueError("Test failure")
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)
        
        # Run tick - should fail and rollback
        with pytest.raises(ValueError):
            await TickOrchestrator.run_tick(test_db_session)
        
        # Verify the main transaction was rolled back
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn
        
        # But tick_log should still exist (separate session)
        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log is not None
        assert tick_log.status == TickLogStatus.FAILED

"""
Tests for the TickOrchestrator.

Tests the tick orchestration system including atomicity, error handling,
and proper tick_log persistence across rollbacks.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from core.tick.orchestrator import TickOrchestrator, TickPhase
from modules._00_core.models import GameClock, Nation, Player, Province, ScheduledAction, ScheduledActionStatus, TickLog, TickLogStatus
from modules._00_core.service import ScheduledActionService
from modules._00_core.tick_handler import finalize_tick, register_tick_handlers


class TestTickOrchestrator:
    """Tests for TickOrchestrator."""
    
    @pytest.fixture(autouse=True)
    async def setup(self):
        """Setup and teardown for each test."""
        # Clear handlers before each test
        TickOrchestrator.clear_handlers()
        # Register the finalize callback
        register_tick_handlers()
        yield
        # Clear handlers after each test
        TickOrchestrator.clear_handlers()
    
    async def _create_game_clock(self, session):
        """Helper to create a game clock."""
        clock = GameClock(id=1, current_turn=0, last_tick_at=None, next_tick_at=datetime.now(timezone.utc))
        session.add(clock)
        await session.flush()
        return clock
    
    async def _create_nation(self, session):
        """Helper to create a nation with player and provinces."""
        from modules._00_core.config_schema import CoreConfig
        from modules._00_core.service import NationService
        
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
        )
        return nation
    
    @pytest.mark.asyncio
    async def test_run_tick_no_handlers(self, test_db_session):
        """Test that run_tick with no handlers completes and increments current_turn."""
        game_clock = await self._create_game_clock(test_db_session)
        initial_turn = game_clock.current_turn
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Refresh the clock
        await test_db_session.refresh(game_clock)
        
        # Verify turn was incremented
        assert game_clock.current_turn == initial_turn + 1
        assert game_clock.last_tick_at is not None
        assert game_clock.next_tick_at is not None
        
        # Verify tick log was created with COMPLETED status
        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.COMPLETED
        assert tick_log.finished_at is not None
        assert tick_log.error_message is None
    
    @pytest.mark.asyncio
    async def test_run_tick_with_handler(self, test_db_session):
        """Test that run_tick executes registered handlers."""
        game_clock = await self._create_game_clock(test_db_session)
        executed_phases = []
        
        async def dummy_handler(session, turn_number):
            executed_phases.append(turn_number)
        
        # Register a handler
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, dummy_handler)
        
        initial_turn = game_clock.current_turn
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Verify handler was executed
        assert len(executed_phases) == 1
        assert executed_phases[0] == initial_turn + 1
        
        # Verify turn was incremented
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn + 1
    
    @pytest.mark.asyncio
    async def test_run_tick_handler_raises_rollback(self, test_db_session):
        """Test that handler exception causes rollback and tick_log records failure."""
        game_clock = await self._create_game_clock(test_db_session)
        nation = await self._create_nation(test_db_session)
        
        # Create a scheduled action to verify it stays PENDING after rollback
        from modules._00_core.service import FrequencyRule
        action = await ScheduledActionService.submit(
            test_db_session,
            nation_id=nation.id,
            module_slug="test_module",
            action_type="test_action",
            payload={"data": "value"},
            turn_number=1,
            frequency_rule=FrequencyRule.ONCE_PER_TURN,
        )
        action_id = action.id
        
        initial_turn = game_clock.current_turn
        
        # Register a handler that raises
        async def failing_handler(session, turn_number):
            raise ValueError("Simulated handler failure")
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)
        
        # Run tick - should raise
        with pytest.raises(ValueError, match="Simulated handler failure"):
            await TickOrchestrator.run_tick(test_db_session)
        
        # Verify ROLLBACK: current_turn unchanged
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn
        
        # Verify ROLLBACK: action still PENDING (not applied)
        result = await test_db_session.execute(
            select(ScheduledAction).where(ScheduledAction.id == action_id)
        )
        action = result.scalar_one()
        assert action.status == ScheduledActionStatus.PENDING
        
        # Verify tick_log survives rollback with FAILED status
        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.FAILED
        assert tick_log.finished_at is not None
        assert "Simulated handler failure" in tick_log.error_message
    
    @pytest.mark.asyncio
    async def test_run_tick_multiple_phases_order(self, test_db_session):
        """Test that handlers execute in phase order."""
        await self._create_game_clock(test_db_session)
        execution_order = []
        
        async def handler_phase1(session, turn_number):
            execution_order.append("PHASE_1")
        
        async def handler_phase2(session, turn_number):
            execution_order.append("PHASE_2")
        
        async def handler_phase3(session, turn_number):
            execution_order.append("PHASE_3")
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, handler_phase1)
        TickOrchestrator.register(TickPhase.PHASE_2_PRODUCTION, handler_phase2)
        TickOrchestrator.register(TickPhase.PHASE_3_CONSUMPTION, handler_phase3)
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Verify execution order
        assert execution_order == ["PHASE_1", "PHASE_2", "PHASE_3"]
    
    @pytest.mark.asyncio
    async def test_run_tick_multiple_handlers_same_phase(self, test_db_session):
        """Test that multiple handlers in the same phase all execute."""
        await self._create_game_clock(test_db_session)
        execution_count = [0]
        
        async def handler1(session, turn_number):
            execution_count[0] += 1
        
        async def handler2(session, turn_number):
            execution_count[0] += 1
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, handler1)
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, handler2)
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Verify both handlers executed
        assert execution_count[0] == 2
    
    @pytest.mark.asyncio
    async def test_run_tick_all_phases_empty(self, test_db_session):
        """Test that all phases are iterated even with no handlers."""
        game_clock = await self._create_game_clock(test_db_session)
        initial_turn = game_clock.current_turn
        
        await TickOrchestrator.run_tick(test_db_session)
        
        # Should complete successfully
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn + 1
    
    @pytest.mark.asyncio
    async def test_finalize_tick_updates_clock(self, test_db_session):
        """Test that finalize_tick correctly updates the game clock."""
        game_clock = await self._create_game_clock(test_db_session)
        initial_turn = game_clock.current_turn
        next_turn = initial_turn + 1
        
        await finalize_tick(test_db_session, next_turn)
        
        await test_db_session.refresh(game_clock)
        
        assert game_clock.current_turn == next_turn
        assert game_clock.last_tick_at is not None
        assert game_clock.next_tick_at is not None
    
    @pytest.mark.asyncio
    async def test_tick_log_persistence_separate_session(self, test_db_session):
        """Test that tick_log is written in a separate session from the tick transaction."""
        game_clock = await self._create_game_clock(test_db_session)
        initial_turn = game_clock.current_turn
        
        # Register a handler that will fail
        async def failing_handler(session, turn_number):
            raise ValueError("Test failure")
        
        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)
        
        # Run tick - should fail and rollback
        with pytest.raises(ValueError):
            await TickOrchestrator.run_tick(test_db_session)
        
        # Verify the main transaction was rolled back
        await test_db_session.refresh(game_clock)
        assert game_clock.current_turn == initial_turn
        
        # But tick_log should still exist (separate session)
        result = await test_db_session.execute(
            select(TickLog).where(TickLog.turn_number == initial_turn + 1)
        )
        tick_log = result.scalar_one()
        assert tick_log is not None
        assert tick_log.status == TickLogStatus.FAILED
