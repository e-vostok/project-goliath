"""
Domain errors of module 04_orders (Spec 5.3).

They derive from the core base class like every other domain error —
``main.py`` maps their ``code`` to an HTTP status. Player-facing
``message`` is Russian with the concrete reason: the client shows it
next to the offending field (Spec 5.3).
"""

from __future__ import annotations

from modules._00_core.exceptions import CoreDomainError


class OrderDomainError(CoreDomainError):
    """Base for 04_orders domain errors — the core code/message shape."""


class OrderNationRequiredError(OrderDomainError):
    """The author owns no nation — HTTP 403 (Spec 5.3)."""

    code = "ORDER_NATION_REQUIRED"

    def __init__(self):
        super().__init__(
            "Подать приказ может только владелец государства",
            self.code,
        )


class OrderAuthorLimitReachedError(OrderDomainError):
    """
    The author already has ``author.max_unresolved_orders`` orders
    without a verdict — HTTP 409 (Spec 5.3, D14, INV-O15).
    """

    code = "ORDER_AUTHOR_LIMIT_REACHED"

    def __init__(self, limit: int):
        super().__init__(
            f"У вас уже {limit} приказов без вердикта — дождитесь "
            "вердикта по одному из них",
            self.code,
            details={"max_unresolved_orders": limit},
        )


class OrderTitleInvalidError(OrderDomainError):
    """The title failed the Spec 2.5 text checks — HTTP 422."""

    code = "ORDER_TITLE_INVALID"

    def __init__(self, reason: str):
        super().__init__(
            f"Название приказа не подходит: {reason}",
            self.code,
        )


class OrderSummaryInvalidError(OrderDomainError):
    """The summary failed the Spec 2.5 text checks — HTTP 422."""

    code = "ORDER_SUMMARY_INVALID"

    def __init__(self, reason: str):
        super().__init__(
            f"Краткая суть приказа не подходит: {reason}",
            self.code,
        )


class OrderUrlInvalidError(OrderDomainError):
    """The article link failed the format/host/length checks — HTTP 422."""

    code = "ORDER_URL_INVALID"

    def __init__(self, reason: str):
        super().__init__(
            f"Ссылка на статью не подходит: {reason}",
            self.code,
        )


class OrderNotFoundError(OrderDomainError):
    """No order with this public number — HTTP 404 (Spec 5.3)."""

    code = "ORDER_NOT_FOUND"

    def __init__(self, number: int):
        super().__init__(
            f"Приказ №{number} не найден",
            self.code,
            details={"number": number},
        )


class OrderVerdictForbiddenError(OrderDomainError):
    """
    The caller is not the assigned judge — HTTP 403 (Spec 5.3).

    One and the same answer for every reason (no judge yet, another
    judge, the author): a distinct wording per case would leak the
    judge assignment (INV-O5).
    """

    code = "ORDER_VERDICT_FORBIDDEN"

    def __init__(self):
        super().__init__(
            "Вердикт по этому приказу писать нельзя",
            self.code,
        )


class OrderVerdictExistsError(OrderDomainError):
    """A verdict is already written — HTTP 409 (Spec 5.3)."""

    code = "ORDER_VERDICT_EXISTS"

    def __init__(self, number: int):
        super().__init__(
            f"По приказу №{number} уже записан вердикт",
            self.code,
            details={"number": number},
        )


class OrderNumberConflictError(OrderDomainError):
    """
    The public number could not be assigned after the retry budget —
    HTTP 500 (Spec 3.5); the failure is logged as ERROR by the caller.
    """

    code = "ORDER_NUMBER_CONFLICT"

    def __init__(self):
        super().__init__(
            "Не удалось присвоить приказу номер — отправьте приказ ещё раз",
            self.code,
        )
