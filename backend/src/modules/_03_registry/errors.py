"""
Domain errors of module 03_registry (Spec 5.1–5.2, 5.6, 2.5).

They derive from the core base class like every other domain error —
``main.py`` maps their ``code`` to an HTTP status. ``RegistryConfigError``
never reaches HTTP: it aborts the boot before the first request (INV-R3).
"""

from __future__ import annotations

from modules._00_core.exceptions import CoreDomainError


class RegistryDomainError(CoreDomainError):
    """Base for 03_registry domain errors — the core code/message shape."""


class RegistryTableNotFoundError(RegistryDomainError):
    """Unknown ``table_id`` in the rows endpoint — HTTP 404 (Spec 5.2)."""

    code = "REGISTRY_TABLE_NOT_FOUND"

    def __init__(self, table_id: str):
        super().__init__(
            f"Таблица «{table_id}» не найдена",
            self.code,
            details={"table_id": table_id},
        )


class RegistryPlayerNotFoundError(RegistryDomainError):
    """
    Out-of-range ``number`` in the player endpoint — HTTP 404
    (Spec 5.6). The ``int``/``ge=1`` path typing already turns
    non-integers, zero and negatives into the usual 422; this error is
    for a well-formed number beyond the player list.
    """

    code = "REGISTRY_PLAYER_NOT_FOUND"

    def __init__(self, number: int):
        super().__init__(
            f"Игрок №{number} не найден",
            self.code,
            details={"number": number},
        )


class RegistryProviderError(RegistryDomainError):
    """
    A table source returned a cell that violates its column's shape
    (Spec 3.1 step 3, 3.6) or failed mid-load — HTTP 500.

    The log line and the response name the table and the column, never
    the offending values.
    """

    code = "REGISTRY_PROVIDER_FAILED"

    def __init__(self, table_id: str, column_id: str | None = None):
        super().__init__(
            "Источник данных таблицы вернул некорректные данные",
            self.code,
            details={"table_id": table_id, "column_id": column_id},
        )


class RegistryConfigError(RegistryDomainError):
    """
    Startup-fatal config/registry mismatch (Spec 2.5 step 3, INV-R3):
    a table pointing at a source nobody registered, or a column at a
    value key the source never promised. Aborts the boot before the
    first connection — never mapped to an HTTP status.
    """

    code = "REGISTRY_CONFIG_INVALID"

    def __init__(self, message: str):
        super().__init__(message, self.code)
