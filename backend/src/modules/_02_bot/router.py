"""
HTTP routes of module 02_bot (Spec 5.1, 5.2).

``POST /api/v1/bot/callback`` is the module's only public endpoint —
VK calls it without a Bearer token; both status endpoints use the
current-player dependency like every other route of the backend.

Callback answers are always ``text/plain``. The request body, the
callback secret and player message text are never logged (INV-B12);
logs carry only the event type, ``event_id`` and the result. The
endpoint never answers ``remove`` — the group token stays valid even
under a flood of bad events (Spec 5.1).
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security.dependencies import get_current_player
from modules._00_core.models import Player
from modules._02_bot.consent_sync import sync_consent_with_vk
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.dialog import handle_event
from modules._02_bot.events import (
    CallbackEvent,
    EventParseError,
    parse_callback_event,
)
from modules._02_bot.exceptions import BotDisabledError
from modules._02_bot.models import BotVkEvent
from modules._02_bot.schemas import BotStatusResponse
from modules._02_bot.settings import (
    BotEnv,
    BotMode,
    get_bot_mode,
    read_bot_env,
)
from modules._02_bot.startup import get_bot_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bot")

_MAX_BODY_BYTES = 64 * 1024


def _is_active(env: BotEnv) -> bool:
    """«Active» = READY or RUNNING; OFF/MISCONFIGURED act as absent."""
    return get_bot_mode(env) in (BotMode.READY, BotMode.RUNNING)


def _group_id_ok(value: object, expected: str | None) -> bool:
    """VK sends ``group_id`` as int or numeric string (Spec 5.1)."""
    if expected is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == int(expected)
    if isinstance(value, str) and value.isdigit():
        return int(value) == int(expected)
    return False


def _secret_ok(value: object, expected: str | None) -> bool:
    """Constant-time secret comparison on bytes (Spec 5.1)."""
    if not isinstance(value, str) or expected is None:
        return False
    return hmac.compare_digest(
        value.encode("utf-8"), expected.encode("utf-8")
    )


async def _event_seen(session: AsyncSession, event_id: str) -> bool:
    """True when a journal row with this ``event_id`` exists — the
    INSERT failed on the genuine UNIQUE, not on another constraint."""
    return (
        await session.execute(
            select(BotVkEvent.id).where(BotVkEvent.event_id == event_id)
        )
    ).scalar_one_or_none() is not None


@router.post("/callback", response_class=PlainTextResponse)
async def vk_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    """Spec 5.1 — VK Callback API entry point, in the spec's order."""
    env = read_bot_env()
    # Step 1: the bot is off/misconfigured — the route does not exist.
    if not _is_active(env):
        return PlainTextResponse("", status_code=404)

    # Step 2: hard 64 KiB limit — the declared length, then the real one.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                return PlainTextResponse("", status_code=413)
        except ValueError:
            pass  # a broken header falls through to the real-length check
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return PlainTextResponse("", status_code=413)

    # Step 3: JSON object with a string ``type``.
    try:
        data = json.loads(body)
    except ValueError:
        return PlainTextResponse("", status_code=400)
    if not isinstance(data, dict) or not isinstance(data.get("type"), str):
        return PlainTextResponse("", status_code=400)
    event_type = data["type"]

    # Step 4: group_id, then the secret — both answered with an empty 403.
    if not _group_id_ok(data.get("group_id"), env.group_id):
        return PlainTextResponse("", status_code=403)
    if not _secret_ok(data.get("secret"), env.callback_secret):
        return PlainTextResponse("", status_code=403)

    # Step 5: confirmation answers the configured string verbatim and
    # is never journaled.
    if event_type == "confirmation":
        return PlainTextResponse(env.callback_confirmation or "")

    # Step 6: events without a string event_id are acked and skipped.
    event_id = data.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        logger.warning(
            "bot callback: %s event without event_id — skipped",
            event_type,
        )
        return PlainTextResponse("ok")

    # Step 7: a malformed object is a logic error — acked, not journaled.
    try:
        event: CallbackEvent = parse_callback_event(data)
    except EventParseError:
        logger.warning(
            "bot callback: malformed object (type=%s, event_id=%s)",
            event_type,
            event_id,
        )
        return PlainTextResponse("ok")

    config = get_bot_config()
    now = datetime.now(timezone.utc)
    duplicate = False
    try:
        # Step 8: journal row and event work in one transaction. The
        # journal INSERT sits in its own SAVEPOINT so a duplicate
        # event_id rolls back nothing else.
        async with session.begin_nested():
            try:
                async with session.begin_nested():
                    session.add(
                        BotVkEvent(
                            event_id=event_id,
                            event_type=event_type,
                            vk_user_id=event.vk_user_id,
                            received_at=now,
                        )
                    )
                    await session.flush()
            except IntegrityError:
                if await _event_seen(session, event_id):
                    duplicate = True
                else:
                    raise
            if not duplicate:
                await handle_event(session, config, event, event_id, now)
        if not duplicate:
            await session.commit()
    except SQLAlchemyError:
        # Transient DB failure — VK retries on 5xx (Spec 5.1).
        logger.warning(
            "bot callback: db error (type=%s, event_id=%s)",
            event_type,
            event_id,
        )
        return PlainTextResponse("", status_code=500)
    except Exception:
        # Handler logic error — the event's work is rolled back by the
        # savepoint, nothing is journaled, the answer is still ok.
        logger.exception(
            "bot callback: handler failed (type=%s, event_id=%s)",
            event_type,
            event_id,
        )
        return PlainTextResponse("ok")

    logger.info(
        "bot callback: %s (type=%s, event_id=%s)",
        "duplicate" if duplicate else "handled",
        event_type,
        event_id,
    )
    return PlainTextResponse("ok")


def _status_response(
    config: BotConfig,
    env: BotEnv,
    state: str,
    stale: bool,
    throttled: bool,
) -> BotStatusResponse:
    """Spec 5.2 — the same shape for GET and POST, active mode only."""
    return BotStatusResponse(
        enabled=True,
        consent=state,  # type: ignore[arg-type]
        stale=stale,
        throttled=throttled,
        registration_requires_consent=config.consent.required_for_registration,
        chat_url=config.client.chat_url_template.replace(
            "{group_id}", env.group_id or ""
        ),
        consent_poll_interval_seconds=config.client.consent_poll_interval_seconds,
        consent_poll_timeout_seconds=config.client.consent_poll_timeout_seconds,
    )


@router.get("/status", response_model=BotStatusResponse)
async def bot_status(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> BotStatusResponse:
    """Spec 5.2 GET — lazy sync, no consent row while the bot is off."""
    env = read_bot_env()
    if not _is_active(env):
        return BotStatusResponse(
            enabled=False,
            consent="UNKNOWN",
            stale=False,
            throttled=False,
            registration_requires_consent=False,
            chat_url=None,
            consent_poll_interval_seconds=None,
            consent_poll_timeout_seconds=None,
        )
    config = get_bot_config()
    state, stale, throttled = await sync_consent_with_vk(
        session, config, player, force=False
    )
    await session.commit()
    return _status_response(config, env, state, stale, throttled)


@router.post("/consent/refresh", response_model=BotStatusResponse)
async def consent_refresh(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> BotStatusResponse:
    """Spec 5.2 POST — force sync; 409 while the bot is off."""
    env = read_bot_env()
    if not _is_active(env):
        raise BotDisabledError()
    config = get_bot_config()
    state, stale, throttled = await sync_consent_with_vk(
        session, config, player, force=True
    )
    await session.commit()
    return _status_response(config, env, state, stale, throttled)
