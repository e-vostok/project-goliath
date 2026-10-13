"""
Domain exceptions of module 02_bot (Spec Part 5 error format).

They derive from the core base class like every other domain error —
``main.py`` maps their ``code`` to an HTTP status; messages are short,
in Russian, and carry no internals.
"""

from __future__ import annotations

from modules._00_core.exceptions import CoreDomainError


class ConsentRequiredError(CoreDomainError):
    """Registration is blocked until the player allows community
    messages (Spec 3.10) — HTTP 403."""

    def __init__(self):
        super().__init__(
            "Разрешите сообщения от сообщества, чтобы создать "
            "государство",
            "CONSENT_REQUIRED",
        )


class BotDisabledError(CoreDomainError):
    """The bot endpoints were called while the bot is off — HTTP 409."""

    def __init__(self):
        super().__init__(
            "Уведомления бота сейчас отключены",
            "BOT_DISABLED",
        )
