"""
The nation-application («анкета») service of module 00_core (0.13.0
unit 4, Spec applications §1–§4, §7).

The player side of the applications flow: ``save_draft`` keeps a
DRAFT (nothing reserved), ``submit`` turns it PENDING under the
nations advisory lock — reserving its provinces, colour, full and
short name for every other path (APP-1) — and ``cancel`` returns it
to DRAFT. The admin side (return, accept, reviewer choice, the
background worker) is 0.13.0 unit 5 and does not exist yet.

Every state change runs inside the caller's transaction under
``_take_nations_lock`` and announces itself through the application
listener registry — each listener under its own SAVEPOINT, never able
to undo the operation (Spec §7).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core import images
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    ApplicationNotEditableError,
    ApplicationNotFoundError,
    ApplicationNotPendingError,
    CapitalNotInProvincesError,
    NationAlreadyExistsError,
    ProvinceCountOutOfRangeError,
)
from modules._00_core.hooks import (
    STAGE_AFTER_COUNT,
    STAGE_AFTER_FREE,
    ApplicationEvent,
    run_application_listeners,
    run_registration_checks,
)
from modules._00_core.models import (
    Nation,
    NationApplication,
    NationApplicationProvince,
    NationImage,
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
from modules._00_core.service import (
    NationImageView,
    _apply_image,
    _check_color_or_raise,
    _check_name_free,
    _check_short_name_free,
    _load_available_provinces,
    _take_nations_lock,
)

LIVE_STATUSES = ("DRAFT", "PENDING")


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

        Order under the nations lock: re-run the profile format checks
        -> name/short name against nations and other PENDING
        applications -> colour against nations, map colours and other
        PENDING -> provinces exist, free and unreserved -> after_free
        -> province count -> after_count -> capital membership ->
        PENDING write (is_reserved=true on every picked province,
        submitted_at, review_deadline_at, submissions+1, draft_reason
        and return_comment cleared, reviewer NULL — unit 5 picks one)
        -> the SUBMITTED event. The caller commits.
        """
        await _take_nations_lock(session)

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
        application.reviewer_player_id = None
        application.reviewer_assigned_at = None
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
