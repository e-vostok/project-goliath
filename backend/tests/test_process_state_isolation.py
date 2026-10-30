"""
Proof for the autouse ``_process_state_isolation`` fixture in
``tests/conftest.py``: an entry registered through the fixture's own
snapshot/restore API is removed again by the restore — the same path
the fixture drives after every test.
"""

from core.admin.registry import AdminRegistry
from core.tick.orchestrator import TickOrchestrator, TickPhase
from modules._00_core.hooks import (
    get_ownership_listeners,
    register_ownership_listener,
)
from tests.conftest import _restore_process_state, _snapshot_process_state


async def test_snapshot_restore_removes_registered_entries():
    async def listener(session, changes):
        return None

    snapshot = _snapshot_process_state()
    register_ownership_listener("test.isolation_proof", listener)
    AdminRegistry.register_reset("test.isolation_proof", listener)
    TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, listener)
    try:
        assert "test.isolation_proof" in get_ownership_listeners()
        assert "test.isolation_proof" in AdminRegistry.get_reset_hooks()
    finally:
        _restore_process_state(snapshot)
    assert "test.isolation_proof" not in get_ownership_listeners()
    assert "test.isolation_proof" not in AdminRegistry.get_reset_hooks()
    assert listener not in [
        handler
        for handlers in TickOrchestrator._handlers.values()
        for handler in handlers
    ]
