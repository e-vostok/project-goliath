"""
The nation-application («анкета») service of module 00_core (0.13.0
units 4–5, Spec applications §1–§7).

The player side of the applications flow: ``save_draft`` keeps a
DRAFT (nothing reserved), ``submit`` turns it PENDING under the
nations advisory lock — reserving its provinces, colour, full and
short name for every other path (APP-1) — and ``cancel`` returns it
to DRAFT. The admin side: ``accept`` creates the nation from the
application inside one transaction, ``return_application`` sends it
back to an editable DRAFT with a mandatory reason, ``run_pass``
auto-accepts the overdue PENDING rows and assigns reviewers to the
unassigned ones (APP-4).

Every state change runs inside the caller's transaction under
``_take_nations_lock`` and announces itself through the application
listener registry — each listener under its own SAVEPOINT, never able
to undo the operation (Spec §7).
"""

from __future__ import annotations

import logging
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, false, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.security import _admin_vk_user_ids
from modules._00_core import images
from modules._00_core.admin_service import AdminAuditService
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ApplicationNotEditableError,
    ApplicationNotFoundError,
    ApplicationNotPendingError,
    ApplicationSelfReviewError,
    CapitalNotInProvincesError,
    CoreDomainError,
    NationAlreadyExistsError,
    ProvinceCountOutOfRangeError,
    ProvinceNotFoundError,
    ReturnCommentInvalidError,
)
from modules._00_core.hooks import (
    STAGE_AFTER_COUNT,
    STAGE_AFTER_FREE,
    ApplicationEvent,
    OwnershipChange,
    notify_ownership_changed,
    run_application_listeners,
    run_before_all_checks,
    run_registration_checks,
)
from modules._00_core.models import (
    AdminGrant,
    Nation,
    NationApplication,
    NationApplicationProvince,
    NationImage,
    Player,
    Province,
)
from modules._00_core.profile_rules import (
    validate_anthem_url,
    validate_capital_name,
    validate_description,
    validate_gender,
    validate_history_url,
    validate_leader_bio,
    validate_leader_name,
    validate_leader_title,
    validate_motto,
    validate_short_name,
    validate_succession_type,
)
from modules._00_core.reviewer import ReviewerCandidate, reviewer_selector
from modules._00_core.service import (
    NationImageInfo,
    NationImageView,
    RemovedNationImage,
    _apply_image,
    _check_color_or_raise,
    _check_name_free,
    _check_short_name_free,
    _current_turn,
    _load_available_provinces,
    _take_nations_lock,
)

logger = logging.getLogger(__name__)

LIVE_STATUSES = ("DRAFT", "PENDING")

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def _live_application(
    session: AsyncSession, player_id: str
) -> NationApplication | None:
    """The player's live (DRAFT/PENDING) application row, or None.

    ``uq_nation_applications_owner_live`` keeps at most one."""
    result = await session.execute(
        select(NationApplication).where(
            NationApplication.owner_player_id == player_id,
            NationApplication.status.in_(LIVE_STATUSES),
        )
    )
    return result.scalar_one_or_none()


def _validate_profile_fields(
    fields: dict, config: CoreConfig
) -> dict:
    """
    The Part 3 format checks in the nation-creation order (INV-9),
    returning the normalized values to store. ``name`` is stripped
    like in ``create``; ``color_hex`` stays as sent (uppercased at
    submit, the same point create normalizes).
    """
    return {
        "leader_name": validate_leader_name(fields["leader_name"], config),
        "leader_title": validate_leader_title(fields["leader_title"], config),
        "gender": validate_gender(fields["gender"], config),
        "succession_type": validate_succession_type(
            fields["succession_type"], config
        ),
        "history_url": validate_history_url(fields["history_url"], config),
        "short_name": validate_short_name(fields["short_name"], config),
        "motto": validate_motto(fields.get("motto"), config),
        "description": validate_description(fields.get("description"), config),
        "leader_bio": validate_leader_bio(fields.get("leader_bio"), config),
        "capital_name": validate_capital_name(fields["capital_name"], config),
    }


async def _admin_player_ids(session: AsyncSession) -> set[str]:
    """The internal ids of every player holding admin rights — the
    env allowlist plus the granted rows — restricted to players that
    actually exist (Spec applications §5)."""
    ids: set[str] = set()
    env_vk_ids = _admin_vk_user_ids()
    if env_vk_ids:
        rows = await session.execute(
            select(Player.id).where(Player.vk_user_id.in_(env_vk_ids))
        )
        ids.update(row[0] for row in rows)
    grant_rows = await session.execute(select(AdminGrant.player_id))
    ids.update(row[0] for row in grant_rows)
    return ids


async def _pick_reviewer(
    session: AsyncSession, applicant_player_id: str
) -> str | None:
    """Choose the reviewer of one application (Spec §5) through the
    injectable ``reviewer_selector`` — None when no administrator is
    eligible. The selector sees only snapshots; the gathering is the
    only DB touch."""
    admin_ids = await _admin_player_ids(session)
    if not admin_ids:
        return None
    stats = await session.execute(
        select(
            NationApplication.reviewer_player_id,
            func.count().filter(NationApplication.status == "PENDING"),
            func.max(NationApplication.reviewer_assigned_at),
        )
        .where(NationApplication.reviewer_player_id.is_not(None))
        .group_by(NationApplication.reviewer_player_id)
    )
    pending_by: dict[str, int] = {}
    last_by: dict[str, datetime] = {}
    for reviewer_id, pending, last_at in stats.all():
        pending_by[reviewer_id] = pending
        last_by[reviewer_id] = last_at
    candidates = [
        ReviewerCandidate(
            player_id=player_id,
            pending=pending_by.get(player_id, 0),
            last_assigned_at=last_by.get(player_id),
        )
        for player_id in sorted(admin_ids)
    ]
    return reviewer_selector(applicant_player_id, candidates)


def _validate_return_comment(comment: str | None, config: CoreConfig) -> str:
    """APP-7: the return reason is mandatory — 1…comment_max_length
    single-line characters after normalization."""
    if comment is None:
        raise ReturnCommentInvalidError("a comment is required")
    text = comment.strip()
    max_length = config.applications.comment_max_length
    if not text or len(text) > max_length:
        raise ReturnCommentInvalidError(
            f"must be between 1 and {max_length} characters, "
            f"got {len(text)}"
        )
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in text):
        raise ReturnCommentInvalidError(
            "contains control or formatting characters"
        )
    return text


@dataclass(frozen=True)
class WorkerPassStats:
    """The counters of one ``run_pass`` (Spec applications §6)."""

    auto_accepted: int = 0
    auto_failed: int = 0
    reviewers_assigned: int = 0
    errors: int = 0


class ApplicationService:
    """Domain service for nation applications («анкеты»)."""

    @staticmethod
    async def get_me(
        session: AsyncSession, player_id: str
    ) -> NationApplication | None:
        """The player's live application, or None. Read-only."""
        return await _live_application(session, player_id)

    @staticmethod
    async def save_draft(
        session: AsyncSession,
        player_id: str,
        config: CoreConfig,
        *,
        name: str,
        short_name: str,
        color_hex: str,
        province_ids: list[int],
        capital_province_id: int | None,
        capital_name: str,
        leader_name: str,
        leader_title: str,
        history_url: str,
        gender: str,
        succession_type: str,
        motto: str | None = None,
        description: str | None = None,
        leader_bio: str | None = None,
        anthem_url: str | None = None,
    ) -> NationApplication:
        """
        Create or rewrite the player's DRAFT application (Spec §4).

        Check order: a nation exists -> 409 NATION_ALREADY_EXISTS; the
        live application is not in DRAFT -> 409
        APPLICATION_NOT_EDITABLE; the profile fields pass the creation
        format checks in their fixed order. Occupancy of names, colour
        and provinces is NOT checked here — that is the submit's job.
        Every write runs under the nations lock; the caller commits.
        """
        result = await session.execute(
            select(Nation.id).where(Nation.owner_player_id == player_id)
        )
        if result.scalar_one_or_none() is not None:
            raise NationAlreadyExistsError(player_id)

        application = await _live_application(session, player_id)
        if application is not None and application.status != "DRAFT":
            raise ApplicationNotEditableError(application.status)

        # anthem_url keeps its slot in the creation check order but is
        # not stored — the application table has no anthem column.
        validate_anthem_url(anthem_url, config)
        fields = _validate_profile_fields(
            {
                "leader_name": leader_name,
                "leader_title": leader_title,
                "gender": gender,
                "succession_type": succession_type,
                "history_url": history_url,
                "short_name": short_name,
                "motto": motto,
                "description": description,
                "leader_bio": leader_bio,
                "capital_name": capital_name,
            },
            config,
        )

        await _take_nations_lock(session)

        # Re-read under the lock: a PENDING row that appeared between
        # the two reads is rejected the same way.
        application = await _live_application(session, player_id)
        if application is not None and application.status != "DRAFT":
            raise ApplicationNotEditableError(application.status)

        now = datetime.now(UTC)
        # Dedupe keeps the first pick of each province; position is the
        # order of first occurrence in the sent list.
        ordered_ids = list(dict.fromkeys(province_ids))
        # Spec §4: the picked provinces must exist — a dangling id is
        # PROVINCE_NOT_FOUND, never a foreign-key 500 on PostgreSQL or
        # a silent bad row on SQLite.
        ids_to_check = set(ordered_ids)
        if capital_province_id is not None:
            ids_to_check.add(capital_province_id)
        if ids_to_check:
            found = set(
                (
                    await session.execute(
                        select(Province.id).where(Province.id.in_(ids_to_check))
                    )
                ).scalars()
            )
            missing = ids_to_check - found
            if missing:
                raise ProvinceNotFoundError(sorted(missing)[0])
        if capital_province_id is None and ordered_ids:
            capital_province_id = ordered_ids[0]

        values = {
            "name": name.strip(),
            "short_name": fields["short_name"],
            "color_hex": color_hex.upper(),
            "motto": fields["motto"],
            "description": fields["description"],
            "leader_name": fields["leader_name"],
            "leader_title": fields["leader_title"],
            "gender": fields["gender"],
            "succession_type": fields["succession_type"],
            "leader_bio": fields["leader_bio"],
            "history_url": fields["history_url"],
            "capital_province_id": capital_province_id,
            "capital_name": fields["capital_name"],
            "updated_at": now,
        }
        if application is None:
            application = NationApplication(
                id=str(uuid.uuid4()),
                owner_player_id=player_id,
                status="DRAFT",
                submissions=0,
                created_at=now,
                **values,
            )
            session.add(application)
            try:
                async with session.begin_nested():
                    await session.flush()
            except IntegrityError:
                # A concurrent save created the row first: the partial
                # owner index fired. Fold into the winner when it is a
                # DRAFT; refuse when it went PENDING in the meantime.
                concurrent = await _live_application(session, player_id)
                if concurrent is None or concurrent.status != "DRAFT":
                    raise ApplicationNotEditableError(
                        concurrent.status if concurrent is not None else "PENDING"
                    )
                application = concurrent
        for key, value in values.items():
            setattr(application, key, value)

        await session.execute(
            delete(NationApplicationProvince).where(
                NationApplicationProvince.application_id == application.id
            )
        )
        if ordered_ids:
            await session.execute(
                insert(NationApplicationProvince),
                [
                    {
                        "application_id": application.id,
                        "province_id": province_id,
                        "position": position,
                        "is_reserved": False,
                    }
                    for position, province_id in enumerate(ordered_ids)
                ],
            )
        await session.flush()
        return application

    @staticmethod
    async def upload_image(
        session: AsyncSession,
        application_id: str,
        player_id: str,
        kind: str,
        processed: images.ProcessedImage,
    ) -> NationImageView:
        """
        Insert or replace the application's picture row of ``kind`` —
        the same pipeline as ``NationService.replace_image``, with the
        application as the picture's owner. DRAFT only: a PENDING
        application cannot be edited at all (Spec §2).
        """
        application = await session.get(NationApplication, application_id)
        if application is None:
            raise ApplicationNotFoundError(player_id)
        if application.status != "DRAFT":
            raise ApplicationNotEditableError(application.status)

        row = (
            await session.execute(
                select(NationImage).where(
                    NationImage.application_id == application_id,
                    NationImage.kind == kind,
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)

        if row is None:
            try:
                # INSERT through a SAVEPOINT — same race-safe shape as
                # replace_image: the unique key (application_id, kind)
                # turns the loser's INSERT into an IntegrityError,
                # retried once as an UPDATE.
                async with session.begin_nested():
                    await session.execute(
                        insert(NationImage).values(
                            application_id=application_id,
                            kind=kind,
                            sha256=processed.sha256,
                            full_bytes=processed.full,
                            thumb_bytes=processed.thumb,
                            byte_size=processed.byte_size,
                            uploaded_by_player_id=player_id,
                            uploaded_at=now,
                        )
                    )
            except IntegrityError:
                row = (
                    await session.execute(
                        select(NationImage).where(
                            NationImage.application_id == application_id,
                            NationImage.kind == kind,
                        )
                    )
                ).scalar_one()
                _apply_image(row, processed, player_id, now)
        else:
            _apply_image(row, processed, player_id, now)
            await session.flush()

        return NationImageView(kind=kind, sha256=processed.sha256, uploaded_at=now)

    @staticmethod
    async def image_refs(
        session: AsyncSession, application_id: str
    ) -> dict[str, str | None]:
        """{kind: sha256} of the application's uploaded pictures —
        None for a kind never uploaded. Read-only."""
        refs: dict[str, str | None] = {"flag": None, "portrait": None}
        result = await session.execute(
            select(NationImage.kind, NationImage.sha256).where(
                NationImage.application_id == application_id
            )
        )
        for kind, sha256 in result.all():
            refs[kind] = sha256
        return refs

    @staticmethod
    async def submit(
        session: AsyncSession, player_id: str, config: CoreConfig
    ) -> NationApplication:
        """
        Send the DRAFT application for review (Spec §4).

        Order: the player must not already own a nation (an
        administrator may have created one after the draft was saved)
        -> the satellite ``before_all`` checks, exactly as
        ``NationService.create`` runs them (bot consent, Spec 02_bot
        3.10) -> the live application must sit in DRAFT -> the nations
        lock -> re-run the profile format checks -> name/short name
        against nations and other PENDING applications -> colour
        against nations, map colours and other PENDING -> provinces
        exist, free and unreserved -> after_free -> province count ->
        after_count -> capital membership -> PENDING write
        (is_reserved=true on every picked province, submitted_at,
        review_deadline_at, submissions+1, draft_reason and
        return_comment cleared, reviewer NULL — unit 5 picks one) ->
        the SUBMITTED event. The caller commits.
        """
        result = await session.execute(
            select(Nation.id).where(Nation.owner_player_id == player_id)
        )
        if result.scalar_one_or_none() is not None:
            raise NationAlreadyExistsError(player_id)

        await run_before_all_checks(session, player_id)

        application = await _live_application(session, player_id)
        if application is None:
            raise ApplicationNotFoundError(player_id)
        if application.status != "DRAFT":
            raise ApplicationNotEditableError(application.status)

        await _take_nations_lock(session)

        # Re-read under the lock: a concurrent submit may already have
        # flipped this application to PENDING.
        application = await _live_application(session, player_id)
        if application is None:
            raise ApplicationNotFoundError(player_id)
        if application.status != "DRAFT":
            raise ApplicationNotEditableError(application.status)

        # Repeat the Part 3 format checks — the stored values are
        # re-validated exactly as save_draft wrote them (Spec §4).
        fields = _validate_profile_fields(
            {
                "leader_name": application.leader_name or "",
                "leader_title": application.leader_title or "",
                "gender": application.gender or "",
                "succession_type": application.succession_type or "",
                "history_url": application.history_url or "",
                "short_name": application.short_name,
                "motto": application.motto,
                "description": application.description,
                "leader_bio": application.leader_bio,
                "capital_name": application.capital_name or "",
            },
            config,
        )

        await _check_name_free(
            session, application.name, exclude_application_id=application.id
        )
        await _check_short_name_free(
            session,
            fields["short_name"],
            exclude_application_id=application.id,
        )
        await _check_color_or_raise(
            session,
            application.color_hex.upper(),
            config,
            exclude_application_id=application.id,
        )

        province_rows = (
            (
                await session.execute(
                    select(NationApplicationProvince.province_id)
                    .where(
                        NationApplicationProvince.application_id == application.id
                    )
                    .order_by(NationApplicationProvince.position)
                )
            )
            .scalars()
            .all()
        )
        provinces = await _load_available_provinces(session, province_rows)

        await run_registration_checks(STAGE_AFTER_FREE, session, provinces)

        province_count = len(province_rows)
        if (
            province_count < config.nation.min_provinces_per_nation
            or province_count > config.nation.max_provinces_per_nation
        ):
            raise ProvinceCountOutOfRangeError(
                province_count,
                config.nation.min_provinces_per_nation,
                config.nation.max_provinces_per_nation,
            )

        await run_registration_checks(STAGE_AFTER_COUNT, session, provinces)

        capital_id = application.capital_province_id
        if capital_id is None and province_rows:
            capital_id = province_rows[0]
            application.capital_province_id = capital_id
        if capital_id not in set(province_rows):
            raise CapitalNotInProvincesError(capital_id)

        now = datetime.now(UTC)
        application.status = "PENDING"
        application.draft_reason = None
        application.return_comment = None
        application.submissions += 1
        application.submitted_at = now
        application.review_deadline_at = now + timedelta(
            hours=config.applications.review_hours
        )
        reviewer_id = await _pick_reviewer(session, player_id)
        application.reviewer_player_id = reviewer_id
        application.reviewer_assigned_at = (
            now if reviewer_id is not None else None
        )
        application.updated_at = now
        await session.execute(
            update(NationApplicationProvince)
            .where(NationApplicationProvince.application_id == application.id)
            .values(is_reserved=True)
        )
        await session.flush()

        await run_application_listeners(
            session,
            ApplicationEvent(
                kind="SUBMITTED",
                application_id=application.id,
                owner_player_id=player_id,
                reviewer_player_id=application.reviewer_player_id,
            ),
        )
        return application

    @staticmethod
    async def cancel(
        session: AsyncSession, player_id: str
    ) -> NationApplication:
        """
        Withdraw a PENDING application back to DRAFT (Spec §4): the
        reserve lifts, the deadline and reviewer clear, ``draft_reason``
        marks 'cancelled', the row and its pictures stay for the next
        save/submit — then the CANCELLED event. The caller commits.
        """
        await _take_nations_lock(session)

        application = await _live_application(session, player_id)
        if application is None:
            raise ApplicationNotFoundError(player_id)
        if application.status != "PENDING":
            raise ApplicationNotPendingError(application.status)

        now = datetime.now(UTC)
        application.status = "DRAFT"
        application.draft_reason = "cancelled"
        application.submitted_at = None
        application.review_deadline_at = None
        application.reviewer_player_id = None
        application.reviewer_assigned_at = None
        application.updated_at = now
        await session.execute(
            update(NationApplicationProvince)
            .where(NationApplicationProvince.application_id == application.id)
            .values(is_reserved=False)
        )
        await session.flush()

        await run_application_listeners(
            session,
            ApplicationEvent(
                kind="CANCELLED",
                application_id=application.id,
                owner_player_id=player_id,
            ),
        )
        return application

    @staticmethod
    async def reserved_groups(session: AsyncSession) -> list[list[int]]:
        """
        The province groups reserved by PENDING applications — one
        list of province ids per application, in pick order, without
        player or application identifiers (APP-6). Read-only.
        """
        result = await session.execute(
            select(
                NationApplicationProvince.application_id,
                NationApplicationProvince.province_id,
            )
            .join(
                NationApplication,
                NationApplication.id
                == NationApplicationProvince.application_id,
            )
            .where(NationApplication.status == "PENDING")
            .order_by(
                NationApplicationProvince.application_id,
                NationApplicationProvince.position,
            )
        )
        groups: dict[str, list[int]] = {}
        for application_id, province_id in result.all():
            groups.setdefault(application_id, []).append(province_id)
        return list(groups.values())

    @staticmethod
    async def reserved_colors(session: AsyncSession) -> list[str]:
        """The colours held by PENDING applications — for the
        distinguishability calculation of other modules (APP-1)."""
        result = await session.execute(
            select(NationApplication.color_hex).where(
                NationApplication.status == "PENDING"
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def delete_for_player(session: AsyncSession, player_id: str) -> None:
        """
        Remove every application of the player with its province picks
        and pictures — the explicit DELETE the coverage contract
        demands; the FK cascades are only a PostgreSQL safety net.
        Reviewer links on other players' rows are cleared too (SQLite
        runs without FK enforcement). Never commits.
        """
        application_ids = list(
            (
                await session.execute(
                    select(NationApplication.id).where(
                        NationApplication.owner_player_id == player_id
                    )
                )
            ).scalars()
        )
        if application_ids:
            await session.execute(
                delete(NationImage).where(
                    NationImage.application_id.in_(application_ids)
                )
            )
            await session.execute(
                delete(NationApplicationProvince).where(
                    NationApplicationProvince.application_id.in_(application_ids)
                )
            )
            await session.execute(
                delete(NationApplication).where(
                    NationApplication.id.in_(application_ids)
                )
            )
        await session.execute(
            update(NationApplication)
            .where(NationApplication.reviewer_player_id == player_id)
            .values(reviewer_player_id=None)
        )
    @staticmethod
    async def accept(
        session: AsyncSession,
        application_id: str,
        config: CoreConfig,
        *,
        decided_by_player_id: str | None,
        auto: bool = False,
    ) -> tuple[NationApplication, Nation]:
        """
        Decide a PENDING application YES (Spec §4, APP-2/APP-3).

        Only from PENDING — anything else is APPLICATION_NOT_PENDING
        naming the current state; the applicant may never decide their
        own application — APPLICATION_SELF_REVIEW (an auto-accept has
        no decider and skips the check).

        One transaction under the nations lock: the nation is created
        with the same records ``NationService.create`` writes (INV-3,
        ``notify_ownership_changed`` per province, the satellite
        ``after_free``/``after_count`` checks) but WITHOUT the
        ``before_all`` checks and WITHOUT the nation-created hooks;
        the application's own reserve never blocks it
        (``exclude_application_id``). The picture rows are re-pointed
        to the nation; the row becomes ACCEPTED with the reserve
        lifted, then the ACCEPTED event fires. The caller commits and
        writes the audit row (``decided_by_player_id=None`` marks the
        machine decision — ``auto_accepted=True``).
        """
        application = await session.get(NationApplication, application_id)
        if application is None:
            raise ApplicationNotFoundError(application_id)
        if application.status != "PENDING":
            raise ApplicationNotPendingError(application.status)
        if (
            decided_by_player_id is not None
            and decided_by_player_id == application.owner_player_id
        ):
            raise ApplicationSelfReviewError()

        await _take_nations_lock(session)

        # Re-read under the lock: a cancel, a return, another accept
        # or a failed auto-accept may have flipped the row between the
        # first read and the lock — the first decider wins (APP-3).
        await session.refresh(application)
        if application.status != "PENDING":
            raise ApplicationNotPendingError(application.status)

        # INV-1: the applicant must still own no nation — an
        # administrator may have created one since the submit.
        result = await session.execute(
            select(Nation.id).where(
                Nation.owner_player_id == application.owner_player_id
            )
        )
        if result.scalar_one_or_none() is not None:
            raise NationAlreadyExistsError(application.owner_player_id)

        fields = _validate_profile_fields(
            {
                "leader_name": application.leader_name or "",
                "leader_title": application.leader_title or "",
                "gender": application.gender or "",
                "succession_type": application.succession_type or "",
                "history_url": application.history_url or "",
                "short_name": application.short_name,
                "motto": application.motto,
                "description": application.description,
                "leader_bio": application.leader_bio,
                "capital_name": application.capital_name or "",
            },
            config,
        )

        await _check_name_free(
            session, application.name, exclude_application_id=application.id
        )
        await _check_short_name_free(
            session,
            fields["short_name"],
            exclude_application_id=application.id,
        )
        await _check_color_or_raise(
            session,
            application.color_hex.upper(),
            config,
            exclude_application_id=application.id,
        )

        province_rows = (
            (
                await session.execute(
                    select(NationApplicationProvince.province_id)
                    .where(
                        NationApplicationProvince.application_id
                        == application.id
                    )
                    .order_by(NationApplicationProvince.position)
                )
            )
            .scalars()
            .all()
        )
        provinces = await _load_available_provinces(
            session, province_rows, application.id
        )

        await run_registration_checks(STAGE_AFTER_FREE, session, provinces)

        province_count = len(province_rows)
        if (
            province_count < config.nation.min_provinces_per_nation
            or province_count > config.nation.max_provinces_per_nation
        ):
            raise ProvinceCountOutOfRangeError(
                province_count,
                config.nation.min_provinces_per_nation,
                config.nation.max_provinces_per_nation,
            )

        await run_registration_checks(STAGE_AFTER_COUNT, session, provinces)

        capital_id = application.capital_province_id
        if capital_id is None and province_rows:
            capital_id = province_rows[0]
            application.capital_province_id = capital_id
        if capital_id not in set(province_rows):
            raise CapitalNotInProvincesError(capital_id)

        # INV-3: the nation row and the province claims — the same
        # write set NationService.create produces, minus the
        # before_all checks and the nation_created hooks (APP-2).
        turn = await _current_turn(session)
        now = datetime.now(UTC)
        nation = Nation(
            id=str(uuid.uuid4()),
            owner_player_id=application.owner_player_id,
            name=application.name,
            color_hex=application.color_hex.upper(),
            leader_name=fields["leader_name"],
            leader_title=fields["leader_title"],
            history_url=fields["history_url"],
            short_name=fields["short_name"],
            gender=fields["gender"],
            succession_type=fields["succession_type"],
            motto=fields["motto"],
            description=fields["description"],
            leader_bio=fields["leader_bio"],
            anthem_url=None,
            capital_province_id=capital_id,
            capital_name=fields["capital_name"],
            created_at=now,
            created_turn=turn,
        )
        session.add(nation)
        await session.flush()

        ordered = sorted(provinces, key=lambda p: p.id)
        for province in ordered:
            province.nation_id = nation.id
        await notify_ownership_changed(
            session,
            [
                OwnershipChange(
                    province_id=province.id,
                    prev_nation_id=None,
                    new_nation_id=nation.id,
                    new_name=nation.name,
                    new_short_name=nation.short_name,
                    new_color=nation.color_hex,
                    turn=turn,
                )
                for province in ordered
            ],
        )

        # The application's pictures become the nation's (Spec §1) —
        # rows re-pointed, bytes and URLs unchanged.
        await session.execute(
            update(NationImage)
            .where(NationImage.application_id == application.id)
            .values(application_id=None, nation_id=nation.id)
        )

        application.status = "ACCEPTED"
        application.accepted_nation_id = nation.id
        application.decided_at = now
        application.decided_by_player_id = decided_by_player_id
        application.auto_accepted = auto
        application.updated_at = now
        await session.execute(
            update(NationApplicationProvince)
            .where(NationApplicationProvince.application_id == application.id)
            .values(is_reserved=False)
        )
        await session.flush()

        await run_application_listeners(
            session,
            ApplicationEvent(
                kind="ACCEPTED",
                application_id=application.id,
                owner_player_id=application.owner_player_id,
                reviewer_player_id=application.reviewer_player_id,
                auto=auto,
            ),
        )
        return application, nation

    @staticmethod
    async def return_application(
        session: AsyncSession,
        application_id: str,
        decider_player_id: str,
        comment: str | None,
        config: CoreConfig,
    ) -> NationApplication:
        """
        Send a PENDING application back to an editable DRAFT (Spec §4):
        ``draft_reason='returned'``, the mandatory normalized comment
        (APP-7 — invalid is RETURN_COMMENT_INVALID), the reserve
        lifted, deadline and reviewer cleared — then the RETURNED
        event. PENDING only, never by the applicant (APP-3). The
        caller commits and writes the audit row.
        """
        comment = _validate_return_comment(comment, config)

        application = await session.get(NationApplication, application_id)
        if application is None:
            raise ApplicationNotFoundError(application_id)
        if application.status != "PENDING":
            raise ApplicationNotPendingError(application.status)
        if decider_player_id == application.owner_player_id:
            raise ApplicationSelfReviewError()

        await _take_nations_lock(session)
        await session.refresh(application)
        if application.status != "PENDING":
            raise ApplicationNotPendingError(application.status)

        now = datetime.now(UTC)
        application.status = "DRAFT"
        application.draft_reason = "returned"
        application.return_comment = comment
        application.submitted_at = None
        application.review_deadline_at = None
        application.reviewer_player_id = None
        application.reviewer_assigned_at = None
        application.updated_at = now
        await session.execute(
            update(NationApplicationProvince)
            .where(NationApplicationProvince.application_id == application.id)
            .values(is_reserved=False)
        )
        await session.flush()

        await run_application_listeners(
            session,
            ApplicationEvent(
                kind="RETURNED",
                application_id=application.id,
                owner_player_id=application.owner_player_id,
                comment=comment,
            ),
        )
        return application

    @staticmethod
    async def delete_image_admin(
        session: AsyncSession, application_id: str, kind: str
    ) -> RemovedNationImage | None:
        """
        The administrator's picture removal for a DRAFT or PENDING
        application (Spec §4) — the same shape as
        ``NationService.delete_image``: the row goes, its sha256 URL
        turns 404 on commit, the application keeps its state. Returns
        the pre-delete description for the journal, ``None`` when the
        application has no such picture. The caller commits and
        writes the audit row.
        """
        application = await session.get(NationApplication, application_id)
        if application is None:
            raise ApplicationNotFoundError(application_id)
        if application.status not in LIVE_STATUSES:
            raise ApplicationNotPendingError(application.status)
        row = (
            await session.execute(
                select(NationImage).where(
                    NationImage.application_id == application_id,
                    NationImage.kind == kind,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        removed = RemovedNationImage(
            info=NationImageInfo(
                url=images.image_url(row.sha256, "full"),
                thumb_url=images.image_url(row.sha256, "thumb"),
                uploaded_at=row.uploaded_at,
                uploaded_by_player_id=row.uploaded_by_player_id,
                size_bytes=len(row.full_bytes),
            ),
            sha256=row.sha256,
        )
        await session.delete(row)
        await session.flush()
        return removed

    @staticmethod
    async def _auto_accept_guarded(
        session: AsyncSession, application_id: str, config: CoreConfig
    ) -> str:
        """
        One auto-accept inside the caller's transaction under a
        SAVEPOINT (Spec §6, APP-4): ``"accepted"`` when the nation was
        created and the ``application.auto_accept`` journal row landed
        (actor 0 — «Система»); ``"failed"`` when a check refused — the
        row falls back to DRAFT with ``draft_reason='failed'``, a
        system comment and the RETURNED event; ``"skipped"`` when the
        row left PENDING before we got to it. The SQLite guard forces
        the driver transaction open before the SAVEPOINT, like
        ``_distribute_guarded`` of 04_orders.
        """
        if session.bind.dialect.name == "sqlite":
            await session.execute(delete(NationApplication).where(false()))
        async with session.begin_nested():
            application = await session.get(NationApplication, application_id)
            if application is None or application.status != "PENDING":
                return "skipped"
            try:
                application, nation = await ApplicationService.accept(
                    session,
                    application_id,
                    config,
                    decided_by_player_id=None,
                    auto=True,
                )
            except CoreDomainError as exc:
                now = datetime.now(UTC)
                comment = (
                    f"Автоприём не удался ({exc.code}): {exc.message}"[:300]
                )
                application.status = "DRAFT"
                application.draft_reason = "failed"
                application.return_comment = comment
                application.submitted_at = None
                application.review_deadline_at = None
                application.reviewer_player_id = None
                application.reviewer_assigned_at = None
                application.updated_at = now
                await session.execute(
                    update(NationApplicationProvince)
                    .where(
                        NationApplicationProvince.application_id
                        == application_id
                    )
                    .values(is_reserved=False)
                )
                await session.flush()
                await run_application_listeners(
                    session,
                    ApplicationEvent(
                        kind="RETURNED",
                        application_id=application_id,
                        owner_player_id=application.owner_player_id,
                        comment=comment,
                        auto=True,
                    ),
                )
                return "failed"
            await AdminAuditService.record(
                session,
                actor_vk_user_id=0,
                action="application.auto_accept",
                target_type="application",
                target_id=application_id,
                summary=(
                    f"Анкета «{application.short_name}» принята "
                    "автоматически по истечении срока; создано "
                    f"государство «{nation.short_name}»."
                ),
                details={
                    "application_id": application_id,
                    "nation_id": nation.id,
                    "owner_player_id": application.owner_player_id,
                },
            )
            return "accepted"

    @staticmethod
    async def _assign_reviewer_guarded(
        session: AsyncSession, application_id: str
    ) -> bool:
        """
        One conditional reviewer assignment inside the caller's
        transaction under a SAVEPOINT (Spec §5–§6): the row is claimed
        only while still PENDING and reviewer-less, so a racing
        decision wins it (rowcount 0 = lost). The ASSIGNED event
        (distinct from the submit's SUBMITTED) carries the new
        reviewer — the applicant already got his SUBMITTED.
        """
        if session.bind.dialect.name == "sqlite":
            await session.execute(delete(NationApplication).where(false()))
        async with session.begin_nested():
            application = await session.get(NationApplication, application_id)
            if application is None or application.status != "PENDING":
                return False
            reviewer_id = await _pick_reviewer(
                session, application.owner_player_id
            )
            if reviewer_id is None:
                return False
            now = datetime.now(UTC)
            claimed = await session.execute(
                update(NationApplication)
                .where(
                    NationApplication.id == application_id,
                    NationApplication.status == "PENDING",
                    NationApplication.reviewer_player_id.is_(None),
                )
                .values(
                    reviewer_player_id=reviewer_id,
                    reviewer_assigned_at=now,
                )
            )
            if claimed.rowcount == 0:
                return False
            await run_application_listeners(
                session,
                ApplicationEvent(
                    kind="ASSIGNED",
                    application_id=application_id,
                    owner_player_id=application.owner_player_id,
                    reviewer_player_id=reviewer_id,
                ),
            )
            return True

    @staticmethod
    async def run_pass(
        session_factory: SessionFactory,
        config: CoreConfig,
        *,
        now: datetime | None = None,
    ) -> WorkerPassStats:
        """
        One background pass of Spec §6 — the worker's step and a
        standalone testable unit.

        Part A, auto-accept: every PENDING application whose
        ``review_deadline_at`` is in the past, oldest deadline first;
        each decided in its own session and transaction — a failure
        of one row is logged, counted and never stops the pass
        (APP-4). Part B, reviewer assignment: PENDING rows without a
        reviewer get the Spec §5 pick, each in its own transaction.
        Never raises for a single bad row.
        """
        moment = now if now is not None else datetime.now(UTC)
        auto_accepted = auto_failed = assigned = errors = 0

        async with session_factory() as session:
            overdue_ids = (
                (
                    await session.execute(
                        select(NationApplication.id)
                        .where(
                            NationApplication.status == "PENDING",
                            NationApplication.review_deadline_at.is_not(None),
                            NationApplication.review_deadline_at <= moment,
                        )
                        .order_by(
                            NationApplication.review_deadline_at,
                            NationApplication.id,
                        )
                    )
                )
                .scalars()
                .all()
            )

        for application_id in overdue_ids:
            try:
                async with session_factory() as session:
                    async with session.begin():
                        outcome = await ApplicationService._auto_accept_guarded(
                            session, application_id, config
                        )
            except Exception:
                errors += 1
                logger.exception(
                    "00_core applications pass: auto-accept failed for %s",
                    application_id,
                )
                continue
            if outcome == "accepted":
                auto_accepted += 1
            elif outcome == "failed":
                auto_failed += 1

        async with session_factory() as session:
            waiting_ids = (
                (
                    await session.execute(
                        select(NationApplication.id)
                        .where(
                            NationApplication.status == "PENDING",
                            NationApplication.reviewer_player_id.is_(None),
                        )
                        .order_by(
                            NationApplication.submitted_at,
                            NationApplication.id,
                        )
                    )
                )
                .scalars()
                .all()
            )

        for application_id in waiting_ids:
            try:
                async with session_factory() as session:
                    async with session.begin():
                        done = await ApplicationService._assign_reviewer_guarded(
                            session, application_id
                        )
            except Exception:
                errors += 1
                logger.exception(
                    "00_core applications pass: reviewer assignment "
                    "failed for %s",
                    application_id,
                )
                continue
            if done:
                assigned += 1

        return WorkerPassStats(
            auto_accepted=auto_accepted,
            auto_failed=auto_failed,
            reviewers_assigned=assigned,
            errors=errors,
        )
