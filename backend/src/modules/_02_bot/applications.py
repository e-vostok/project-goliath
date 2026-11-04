"""
Application messages of module 02_bot (Spec 4.8 — 0.13.0 unit 6; the
event contract is Spec applications §7).

Registered as ``02_bot.applications`` during ``startup_bot()`` —
always registered; the listener itself gates on the bot mode, so an
OFF bot returns without writing. Each invocation runs inside the
operation's transaction under its own SAVEPOINT: a failure rolls back
only this listener's rows and never the decision (Spec applications
§7).

Mapping: ``SUBMITTED`` -> ``APPLICATION_RECEIVED`` to the applicant,
plus ``APPLICATION_REVIEW_REQUEST`` to every administrator except
the applicant (each under his own SAVEPOINT — one failure never
stops the others); ``RETURNED`` -> ``APPLICATION_RETURNED``;
``ACCEPTED`` -> ``APPLICATION_ACCEPTED`` or ``_AUTO`` on ``auto``;
``CANCELLED`` -> nothing.

Every text links into the Mini App through ``BotService.app_link``;
without ``VK_APP_ID`` nothing is enqueued and one warning is logged —
the same rule as the order notifications of 04_orders. A missing
consent is decided inside ``enqueue`` (``SKIPPED_NO_CONSENT``): the
message is skipped and never raises, never blocks the decision — the
shield and the panel stay the administrator's channels.

Data sovereignty: the listener never touches core tables — the
application's name, deadline, submission counter and the admin
audience come through ``ApplicationService.notification_view`` and
``ApplicationService.admin_recipient_ids``, and the deadline renders
in ``tick_timezone`` of ``configs/00_core.yaml``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.application_service import (
    ApplicationNotificationView,
    ApplicationService,
)
from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import ApplicationEvent
from modules._02_bot.settings import is_bot_active

logger = logging.getLogger(__name__)

APPLICATION_RECEIVED = "APPLICATION_RECEIVED"
APPLICATION_RETURNED = "APPLICATION_RETURNED"
APPLICATION_ACCEPTED = "APPLICATION_ACCEPTED"
APPLICATION_ACCEPTED_AUTO = "APPLICATION_ACCEPTED_AUTO"
APPLICATION_REVIEW_REQUEST = "APPLICATION_REVIEW_REQUEST"


def _genitive_month(name: str) -> str:
    """
    Russian genitive of a configured month name («1 ноября»): -ь/-й ->
    -я (январь -> января, май -> мая), -т -> -та (март -> марта,
    август -> августа); other endings stay verbatim — the same rule as
    the panel's «Следующий ход» tile (00_core admin_hooks).
    """
    if name.endswith(("ь", "й")):
        return name[:-1] + "я"
    if name.endswith("т"):
        return name + "а"
    return name


def _deadline_text(moment: datetime | None) -> str:
    """
    «1 ноября, 14:20» — the review deadline rendered in
    ``tick.tick_timezone`` of ``configs/00_core.yaml``; a missing
    deadline renders ``—`` (PENDING rows always carry one).
    """
    if moment is None:
        return "—"
    if moment.tzinfo is None:
        # SQLite returns naive datetimes for timezone=True columns.
        moment = moment.replace(tzinfo=UTC)
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    local = moment.astimezone(ZoneInfo(config.tick.tick_timezone))
    month = _genitive_month(config.calendar.month_names[local.month - 1])
    return f"{local.day} {month}, {local:%H:%M}"


async def _enqueue_review_request(
    session: AsyncSession,
    *,
    application_id: str,
    admin_player_id: str,
    view: ApplicationNotificationView,
) -> None:
    """
    ``APPLICATION_REVIEW_REQUEST`` to one administrator; the link
    opens the application's own window (``#application/<id>``).
    """
    from modules._02_bot.service import BotService

    await BotService.enqueue(
        session,
        type_key=APPLICATION_REVIEW_REQUEST,
        player_id=admin_player_id,
        event_key=(
            f"application_{APPLICATION_REVIEW_REQUEST}:"
            f"{application_id}:{view.submissions}"
        ),
        variables={
            "nation_name": view.name,
            "application_link": BotService.app_link(
                f"application/{application_id}"
            ),
            "deadline": _deadline_text(view.review_deadline_at),
        },
    )


async def application_listener(
    session: AsyncSession, event: ApplicationEvent
) -> None:
    """Spec 4.8 — the ``(session, ApplicationEvent)`` listener contract."""
    # CANCELLED writes nothing; an OFF/MISCONFIGURED bot returns
    # without writing — the listener must stay safe with the bot off.
    if event.kind == "CANCELLED" or not is_bot_active():
        return
    # Imported lazily: service -> startup would otherwise close an
    # import cycle back into this module (same shape as nation_hook).
    from modules._02_bot.service import BotService

    player_link = BotService.app_link("application")
    if player_link is None:
        logger.warning(
            "application_notification_skipped_no_app_id: %s event for "
            "application %s — VK_APP_ID is not set, notifications not "
            "enqueued",
            event.kind,
            event.application_id,
        )
        return
    view = await ApplicationService.notification_view(
        session, event.application_id
    )
    if view is None:
        # The event fires inside the operation's transaction — the row
        # always exists; the guard stays defensive.
        return

    suffix = f"{event.application_id}:{view.submissions}"
    if event.kind == "SUBMITTED":
        await BotService.enqueue(
            session,
            type_key=APPLICATION_RECEIVED,
            player_id=event.owner_player_id,
            event_key=f"application_{APPLICATION_RECEIVED}:{suffix}",
            variables={
                "nation_name": view.name,
                "application_link": player_link,
                "deadline": _deadline_text(view.review_deadline_at),
            },
        )
        admin_ids = await ApplicationService.admin_recipient_ids(
            session, exclude_player_id=event.owner_player_id
        )
        for admin_id in sorted(admin_ids):
            try:
                async with session.begin_nested():
                    await _enqueue_review_request(
                        session,
                        application_id=event.application_id,
                        admin_player_id=admin_id,
                        view=view,
                    )
            except Exception as exc:
                logger.warning(
                    "application_review_request_failed player=%s error=%s",
                    admin_id,
                    type(exc).__name__,
                )
    elif event.kind == "RETURNED":
        await BotService.enqueue(
            session,
            type_key=APPLICATION_RETURNED,
            player_id=event.owner_player_id,
            event_key=f"application_{APPLICATION_RETURNED}:{suffix}",
            variables={
                "nation_name": view.name,
                "application_link": player_link,
                "comment": event.comment or "",
            },
        )
    elif event.kind == "ACCEPTED":
        type_key = (
            APPLICATION_ACCEPTED_AUTO if event.auto else APPLICATION_ACCEPTED
        )
        await BotService.enqueue(
            session,
            type_key=type_key,
            player_id=event.owner_player_id,
            event_key=f"application_{type_key}:{suffix}",
            variables={
                "nation_name": view.name,
                "application_link": player_link,
            },
        )
