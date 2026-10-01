"""
Tests for the AdminRegistry hook registry.

Anti-Mock Guard: registered hooks are exercised against the real
in-memory test DB session fixture, not mocked.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select

from core.admin.registry import AdminRegistry
from modules._00_core.models import Player


@pytest.fixture(autouse=True)
def clean_registry():
    """Isolate each test from class-level registry state."""
    AdminRegistry.clear_handlers()
    yield
    AdminRegistry.clear_handlers()


class TestAdminRegistry:
    """Tests for AdminRegistry hook registration and retrieval."""

    async def _noop_reset(self, session):
        return None

    async def _noop_view(self, session):
        return {}

    def test_register_and_get_reset_hooks(self):
        """Registered reset hooks are returned keyed by module_slug."""
        AdminRegistry.register_reset("mod_a", self._noop_reset)
        AdminRegistry.register_reset("mod_b", self._noop_reset)

        hooks = AdminRegistry.get_reset_hooks()

        assert list(hooks) == ["mod_a", "mod_b"]
        assert hooks["mod_a"] == self._noop_reset

    def test_register_and_get_state_view_hooks(self):
        """Registered state-view hooks are returned keyed by module_slug."""
        AdminRegistry.register_state_view("mod_a", self._noop_view)
        AdminRegistry.register_state_view("mod_b", self._noop_view)

        hooks = AdminRegistry.get_state_view_hooks()

        assert list(hooks) == ["mod_a", "mod_b"]
        assert hooks["mod_b"] == self._noop_view

    def test_insertion_order_preserved(self):
        """get_*_hooks preserve registration order across hook types."""
        AdminRegistry.register_state_view("zeta", self._noop_view)
        AdminRegistry.register_state_view("alpha", self._noop_view)
        AdminRegistry.register_state_view("mid", self._noop_view)

        assert list(AdminRegistry.get_state_view_hooks()) == [
            "zeta", "alpha", "mid",
        ]

    def test_duplicate_reset_slug_raises(self):
        """Registering the same slug twice for reset hooks raises ValueError."""
        AdminRegistry.register_reset("mod_a", self._noop_reset)

        with pytest.raises(ValueError, match="mod_a"):
            AdminRegistry.register_reset("mod_a", self._noop_reset)

    def test_duplicate_state_view_slug_raises(self):
        """Registering the same slug twice for state views raises ValueError."""
        AdminRegistry.register_state_view("mod_a", self._noop_view)

        with pytest.raises(ValueError, match="mod_a"):
            AdminRegistry.register_state_view("mod_a", self._noop_view)

    def test_same_slug_across_hook_types_allowed(self):
        """The same module_slug may own one hook of each type."""
        AdminRegistry.register_reset("mod_a", self._noop_reset)
        AdminRegistry.register_state_view("mod_a", self._noop_view)

        assert "mod_a" in AdminRegistry.get_reset_hooks()
        assert "mod_a" in AdminRegistry.get_state_view_hooks()

    def test_clear_handlers_empties_both_registries(self):
        """clear_handlers wipes reset and state-view hooks alike."""
        AdminRegistry.register_reset("mod_a", self._noop_reset)
        AdminRegistry.register_state_view("mod_a", self._noop_view)

        AdminRegistry.clear_handlers()

        assert AdminRegistry.get_reset_hooks() == {}
        assert AdminRegistry.get_state_view_hooks() == {}

    @pytest.mark.asyncio
    async def test_registered_hooks_run_against_real_session(
        self, test_db_session
    ):
        """Hooks retrieved from the registry execute on the real test DB."""
        test_db_session.add(Player(vk_user_id=11111))
        await test_db_session.flush()

        async def reset_hook(session):
            await session.execute(delete(Player))

        async def view_hook(session):
            result = await session.execute(
                select(func.count()).select_from(Player)
            )
            return {"player_count": result.scalar_one()}

        AdminRegistry.register_state_view("00_core", view_hook)
        AdminRegistry.register_reset("00_core", reset_hook)

        view = AdminRegistry.get_state_view_hooks()["00_core"]
        assert await view(test_db_session) == {"player_count": 1}

        reset = AdminRegistry.get_reset_hooks()["00_core"]
        await reset(test_db_session)
        assert (await view(test_db_session))["player_count"] == 0
