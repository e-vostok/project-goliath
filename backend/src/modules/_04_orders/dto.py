"""
Request/response DTOs of module 04_orders (Spec 5.2).

Every model is ``extra="forbid"`` — a client typo or a reserved field
(``verdict_effects`` is never accepted, INV-O13) fails validation instead
of being silently dropped. No DTO carries the judge's identity or any
VK id (INV-O5).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class _Strict(BaseModel):
    """Base for the module's DTOs: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class OrderCreateRequest(_Strict):
    """``POST /orders`` body (Spec 5.2)."""

    title: str
    summary: str
    article_url: str
    # Idempotency key of the submission (INV-O9); a repeat with the same
    # value returns the existing order instead of creating a second one.
    client_request_id: uuid.UUID


class OrderRulesDTO(_Strict):
    """``GET /orders/rules`` — form limits plus the author's counter."""

    title_min_length: int
    title_max_length: int
    summary_min_length: int
    summary_max_length: int
    url_max_length: int
    max_unresolved_orders: int
    unresolved_orders: int


class NationMarkDTO(_Strict):
    """The author-nation snapshot shown next to the order."""

    name: str
    color: str


class VerdictDTO(_Strict):
    """The written verdict's public fields (no judge data, INV-O5)."""

    title: str
    summary: str
    article_url: str


class OrderDetailDTO(_Strict):
    """``POST /orders`` and ``GET /orders/{number}`` payload (Spec 5.2)."""

    number: int
    nation: NationMarkDTO
    title: str
    summary: str
    article_url: str
    distributed: bool
    verdict: VerdictDTO | None
    overdue: bool
    can_write_verdict: bool


class AssignedOrderDTO(_Strict):
    """One item of ``GET /orders/assigned`` — the caller's queue."""

    number: int
    nation: NationMarkDTO
    title: str
    summary: str
    article_url: str
    # The deadline as shown to the judge: «15.10.2026 21:21» in
    # tick.tick_timezone (Spec 5.2).
    deadline_text: str
    overdue: bool


class AssignedOrdersDTO(_Strict):
    """
    ``GET /orders/assigned`` payload (Spec 5.2): every order of the
    current player without a verdict, soonest deadline first.
    """

    items: list[AssignedOrderDTO]
