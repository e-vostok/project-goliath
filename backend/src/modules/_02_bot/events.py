"""
Inbound Callback API event parsing of module 02_bot (Spec 5.1, 3.9).

Pure functions only — no database, no VK, no logging. A malformed
``object`` raises :class:`EventParseError`, which the callback endpoint
treats as the Spec-5.1-step-8 logic error: the request is answered
``200 ok`` and no journal row is left behind.

Message text is never returned — ``MessageNew.text`` is consumed only
by the command matcher inside the same request and never stored
(INV-B12).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class EventParseError(Exception):
    """The event's ``object`` does not match the expected shape."""


@dataclass(frozen=True)
class MessageNew:
    """The fields of a ``message_new`` event the dialog needs."""

    from_id: int | None
    peer_id: int | None
    out: int
    text: str
    payload: str | None  # the raw JSON string, parsed lazily by the dialog


@dataclass(frozen=True)
class CallbackEvent:
    """One parsed callback: journal fields plus the typed payload."""

    event_type: str
    vk_user_id: int | None
    message: MessageNew | None = None


def _opt_int(message: Mapping[str, Any], key: str) -> int | None:
    value = message.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventParseError(f"message_new.{key} is not an int")
    return value


def _require_user_id(obj: Any) -> int:
    if not isinstance(obj, dict):
        raise EventParseError("event object is not a dict")
    value = obj.get("user_id")
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventParseError("object.user_id is missing or not an int")
    return value


def _parse_message_new(obj: Any) -> MessageNew:
    if not isinstance(obj, dict):
        raise EventParseError("message_new object is not a dict")
    message = obj.get("message")
    if message is None:
        # Pre-5.103 flat form: the object IS the message (Spec 5.1).
        message = obj
    if not isinstance(message, dict):
        raise EventParseError("message_new object.message is not a dict")
    text = message.get("text")
    if text is not None and not isinstance(text, str):
        raise EventParseError("message_new.text is not a string")
    payload = message.get("payload")
    if payload is not None and not isinstance(payload, str):
        raise EventParseError("message_new.payload is not a string")
    return MessageNew(
        from_id=_opt_int(message, "from_id"),
        peer_id=_opt_int(message, "peer_id"),
        out=_opt_int(message, "out") or 0,
        text=text or "",
        payload=payload,
    )


def parse_callback_event(body: Mapping[str, Any]) -> CallbackEvent:
    """
    Parse the callback body (``type`` already verified as a string).

    ``vk_user_id`` is what the journal row stores: ``object.user_id``
    for allow/deny, ``from_id`` for ``message_new``, the same field of
    unknown event types when it happens to be there.
    """
    event_type = body["type"]
    obj = body.get("object")
    if event_type in ("message_allow", "message_deny"):
        user_id = _require_user_id(obj)
        return CallbackEvent(event_type=event_type, vk_user_id=user_id)
    if event_type == "message_new":
        message = _parse_message_new(obj)
        return CallbackEvent(
            event_type=event_type,
            vk_user_id=message.from_id,
            message=message,
        )
    vk_user_id = None
    if (
        isinstance(obj, dict)
        and isinstance(obj.get("user_id"), int)
        and not isinstance(obj["user_id"], bool)
    ):
        vk_user_id = obj["user_id"]
    return CallbackEvent(event_type=event_type, vk_user_id=vk_user_id)
