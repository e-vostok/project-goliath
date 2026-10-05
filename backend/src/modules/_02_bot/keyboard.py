"""
VK keyboards of module 02_bot (Spec 5.5).

The persistent panel (``one_time=false, inline=false``) is sent with
every outgoing message — VK keeps it until a replacement arrives.
MEMBER (has a nation): «Статус» + «Помощь»; GUEST: «Создать
государство» (open_app, only when VK_APP_ID is set) + «Помощь».
The "Помощь" answer additionally carries an inline keyboard of
open_link buttons — one per row, only for the non-null help URLs.

``dumps`` produces the compact JSON ``messages.send`` takes and is the
last line of defense for the documented VK limits: label <= 40 chars,
payload a JSON string <= 255 chars wrapped in braces.
"""

from __future__ import annotations

import json
from typing import Literal

from modules._02_bot.config_schema import BotConfig

KeyboardVariant = Literal["MEMBER", "GUEST"]

_LABEL_LIMIT = 40
_PAYLOAD_LIMIT = 255


def _text_button(label: str, payload: dict) -> dict:
    return {
        "action": {
            "type": "text",
            "label": label,
            "payload": json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ),
        }
    }


def build_persistent_keyboard(
    variant: KeyboardVariant, config: BotConfig, app_id: int | None
) -> dict:
    """The persistent one-row panel for the player's state (D3)."""
    labels = config.dialog.labels
    if variant == "MEMBER":
        row = [
            _text_button(labels.status, {"cmd": "status"}),
            _text_button(labels.help, {"cmd": "help"}),
        ]
    else:  # GUEST
        row = []
        if app_id is not None:
            row.append(
                {
                    "action": {
                        "type": "open_app",
                        "label": labels.register_nation,
                        "app_id": app_id,
                        "hash": "register",
                    }
                }
            )
        row.append(_text_button(labels.help, {"cmd": "help"}))
    return {"one_time": False, "inline": False, "buttons": [row]}


def build_help_inline_keyboard(config: BotConfig) -> dict | None:
    """
    The inline keyboard attached to the «Помощь» answer only: one
    open_link button per row for every non-null help URL; None when
    every link is hidden.
    """
    labels = config.dialog.labels
    links = config.dialog.help
    rows = [
        [{"action": {"type": "open_link", "label": label, "link": url}}]
        for label, url in (
            (labels.rules, links.rules_url),
            (labels.regulations, links.regulations_url),
            (labels.contact_admin, links.admin_contact_url),
        )
        if url
    ]
    if not rows:
        return None
    return {"inline": True, "buttons": rows}


def dumps(keyboard: dict) -> str:
    """
    Compact JSON (``ensure_ascii=False``) for ``messages.send``.
    Raises ValueError on any label over 40 chars or any payload that is
    over 255 chars or not a ``{...}`` JSON object string.
    """
    for row in keyboard.get("buttons", []):
        for button in row:
            action = button["action"]
            if len(action["label"]) > _LABEL_LIMIT:
                raise ValueError(
                    f"keyboard label exceeds {_LABEL_LIMIT} characters: "
                    f"{len(action['label'])}"
                )
            payload = action.get("payload")
            if payload is not None and (
                len(payload) > _PAYLOAD_LIMIT
                or not (payload.startswith("{") and payload.endswith("}"))
            ):
                raise ValueError(
                    "keyboard payload must be a JSON object string of "
                    f"at most {_PAYLOAD_LIMIT} characters"
                )
    return json.dumps(keyboard, ensure_ascii=False, separators=(",", ":"))
