"""
Admin grants and audit-log services for module 00_core (0.11.0 unit 3).

Two public services, both working strictly inside the caller's
transaction and never committing:

- ``AdminAuditService`` — appends to and reads the permanent
  ``admin_audit_log`` journal of admin-panel actions.
- ``AdminGrantService`` — manages ``admin_grants``, the
  database-issued admin rights that complement the
  ADMIN_VK_USER_IDS env allowlist. The env parsing itself stays in
  ``core.admin.security`` — importing it here keeps one parser.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.security import _admin_vk_user_ids, is_admin_vk_user
from modules._00_core.exceptions import CoreDomainError, PlayerNotFoundError
from modules._00_core.models import AdminAuditLog, AdminGrant, Player


class RootAdminProtectedError(CoreDomainError):
    """An admin whose vk id sits in ADMIN_VK_USER_IDS cannot be revoked."""

    def __init__(self):
        super().__init__(
            "An administrator from the environment allowlist cannot be revoked",
            "ROOT_ADMIN_PROTECTED",
        )


class LastAdminError(CoreDomainError):
    """The last remaining admin (env allowlist plus grants) cannot be revoked."""

    def __init__(self):
        super().__init__(
            "The last remaining administrator cannot be revoked",
            "LAST_ADMIN",
        )


class AdminAuditService:
    """The permanent journal of admin-panel actions."""

    @staticmethod
    async def record(
        session: AsyncSession,
        actor_vk_user_id: int,
        action: str,
        summary: str,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict | None = None,
    ) -> AdminAuditLog:
        """
        Append one journal row to the CALLER's transaction — never
        commits, so the entry lands or rolls back together with the
        action it describes. ``details`` carries ids and before/after
        values only — never tokens or raw launch params.
        """
        row = AdminAuditLog(
            actor_vk_user_id=actor_vk_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            summary=summary,
            details=details,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def list_recent(
        session: AsyncSession,
        limit: int,
        before_id: int | None = None,
        actor_vk_user_id: int | None = None,
        action: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        tz_name: str = "UTC",
    ) -> list[AdminAuditLog]:
        """
        Newest journal rows first (by id). ``before_id`` is the
        pagination cursor: only rows with id below it are returned.

        Optional filters: ``actor_vk_user_id`` and ``action`` match
        exactly; ``date_from``/``date_to`` are local CALENDAR dates in
        ``tz_name`` (the tick timezone), inclusive on both ends — the
        bounds are shifted 1 µs inward because SQLite stores
        CURRENT_TIMESTAMP as a plain 'YYYY-MM-DD HH:MM:SS' string while
        bound parameters render with microseconds and an offset, and a
        row stamped exactly on the bound must still land inside its
        day. Read-only, never commits.
        """
        stmt = select(AdminAuditLog).order_by(AdminAuditLog.id.desc()).limit(limit)
        if before_id is not None:
            stmt = stmt.where(AdminAuditLog.id < before_id)
        if actor_vk_user_id is not None:
            stmt = stmt.where(AdminAuditLog.actor_vk_user_id == actor_vk_user_id)
        if action is not None:
            stmt = stmt.where(AdminAuditLog.action == action)
        epsilon = timedelta(microseconds=1)
        if date_from is not None:
            start = datetime.combine(
                date_from, time.min, tzinfo=ZoneInfo(tz_name)
            ).astimezone(UTC)
            stmt = stmt.where(AdminAuditLog.created_at > start - epsilon)
        if date_to is not None:
            end = datetime.combine(
                date_to + timedelta(days=1), time.min, tzinfo=ZoneInfo(tz_name)
            ).astimezone(UTC)
            stmt = stmt.where(AdminAuditLog.created_at <= end - epsilon)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def distinct_actors(session: AsyncSession) -> list[int]:
        """Every actor_vk_user_id present in the journal, ascending."""
        result = await session.execute(
            select(AdminAuditLog.actor_vk_user_id)
            .distinct()
            .order_by(AdminAuditLog.actor_vk_user_id)
        )
        return [row[0] for row in result.all()]

    @staticmethod
    async def distinct_actions(session: AsyncSession) -> list[str]:
        """Every action code present in the journal, alphabetical."""
        result = await session.execute(
            select(AdminAuditLog.action).distinct().order_by(AdminAuditLog.action)
        )
        return [row[0] for row in result.all()]


class AdminGrantService:
    """Database-issued admin rights beside the env allowlist."""

    @staticmethod
    async def is_granted(session: AsyncSession, vk_user_id: int) -> bool:
        """
        True when a grant row exists for the player with this vk id —
        read from the database on every call, so a revoked admin loses
        access immediately. Read-only, never commits.
        """
        result = await session.execute(
            select(func.count())
            .select_from(AdminGrant)
            .join(Player, AdminGrant.player_id == Player.id)
            .where(Player.vk_user_id == vk_user_id)
        )
        return result.scalar_one() > 0

    @staticmethod
    async def grant(
        session: AsyncSession, target_player_id: str, by_vk_user_id: int
    ) -> AdminGrant:
        """
        Grant admin rights to a player, inside the caller's
        transaction (never commits). Idempotent: an already granted
        player returns the existing row instead of raising on the
        UNIQUE constraint.
        """
        result = await session.execute(
            select(AdminGrant).where(AdminGrant.player_id == target_player_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing
        player = await session.get(Player, target_player_id)
        if player is None:
            raise PlayerNotFoundError(target_player_id)
        row = AdminGrant(
            player_id=target_player_id, granted_by_vk_user_id=by_vk_user_id
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def revoke(session: AsyncSession, target_player_id: str) -> None:
        """
        Remove a player's admin grant, inside the caller's
        transaction (never commits). Two refusals:

        - ROOT_ADMIN_PROTECTED — the player's vk id sits in
          ADMIN_VK_USER_IDS: env admins can only be removed by editing
          the environment, never through the panel;
        - LAST_ADMIN — after the removal no admin would remain at all
          (env allowlist plus the remaining grants).

        Revoking a player who holds no grant is a no-op.
        """
        player = await session.get(Player, target_player_id)
        if player is None:
            raise PlayerNotFoundError(target_player_id)
        if is_admin_vk_user(player.vk_user_id):
            raise RootAdminProtectedError()
        result = await session.execute(
            select(AdminGrant).where(AdminGrant.player_id == target_player_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return
        remaining = await session.execute(
            select(Player.vk_user_id)
            .join(AdminGrant, AdminGrant.player_id == Player.id)
            .where(AdminGrant.player_id != target_player_id)
        )
        remaining_admins = {r[0] for r in remaining.all()} | _admin_vk_user_ids()
        if not remaining_admins:
            raise LastAdminError()
        await session.delete(row)
        await session.flush()
