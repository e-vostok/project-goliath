"""
VK ``users.get`` client of module 03_registry (Spec 3.4, facts R1–R6).

One ``httpx.AsyncClient`` with ``base_url``, timeout and API version
from ``profiles.*``. Every call is a ``POST /users.get`` with an
``application/x-www-form-urlencoded`` body (``user_ids``, ``fields``,
``v``); the community key travels ONLY in the
``Authorization: Bearer`` header — never in the URL, the form body,
logs, exceptions or ``repr``; response bodies are never logged.

Response parsing follows Spec 3.4 exactly: a returned element without
``deactivated`` and without ``hidden = 1`` is an ``OK`` outcome with
cleaned values; ``deactivated``, ``hidden = 1`` or a requested id
missing from the response is ``UNAVAILABLE``; call errors 30 and 113
bisect the batch — each half is re-requested recursively and a
single-id request resolves to ``UNAVAILABLE``; codes 5, 27, 28 mean
the key is invalid (``INVALID_TOKEN``); everything else — a retryable
``RETRY`` batch failure.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

import httpx

from modules._03_registry.config_schema import ProfilesConfig

logger = logging.getLogger(__name__)

NAME_MAX_LENGTH = 64
PHOTO_URL_MAX_LENGTH = 1024

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_STUB_PHOTO_NAMES = frozenset({"camera_50.png", "camera_100.png"})
# Call errors naming one bad user in the batch (Spec 3.4): the batch is
# split in half; a single id resolves to UNAVAILABLE.
_BISECT_ERROR_CODES = frozenset({30, 113})
# Call errors meaning the access key itself is dead (Spec 3.4, R6).
_INVALID_TOKEN_CODES = frozenset({5, 27, 28})


def clean_name(value: object) -> str | None:
    """
    Spec 3.4 cleaning for ``first_name``/``last_name``: control
    characters and edge spaces removed, capped at 64 characters;
    anything non-string or empty afterwards becomes ``None``.
    """
    if not isinstance(value, str):
        return None
    cleaned = _CONTROL_RE.sub("", value).strip()
    return cleaned[:NAME_MAX_LENGTH] or None


def clean_photo_url(value: object) -> str | None:
    """
    Spec 3.4 cleaning for the avatar URL: only ``https`` and at most
    1024 characters; a ``camera_50.png``/``camera_100.png`` stub (no
    photo uploaded, R3) and anything else invalid become ``None``.
    """
    if not isinstance(value, str) or len(value) > PHOTO_URL_MAX_LENGTH:
        return None
    if value != value.strip() or _CONTROL_RE.search(value):
        return None
    if urlparse(value).scheme != "https":
        return None
    if value.rsplit("/", 1)[-1] in _STUB_PHOTO_NAMES:
        return None
    return value


class OutcomeKind(str, Enum):
    """What the VK boundary answered for one requested id (Spec 3.4)."""

    OK = "OK"                    # user returned, not deactivated/hidden
    UNAVAILABLE = "UNAVAILABLE"  # deactivated, hidden or absent


@dataclass(frozen=True)
class ProfileOutcome:
    """
    The per-player result of one ``users.get`` batch: ``OK`` carries
    the cleaned values, ``UNAVAILABLE`` carries nothing.
    """

    kind: OutcomeKind
    first_name: str | None = None
    last_name: str | None = None
    photo_url: str | None = None


class BatchFailure(str, Enum):
    """Why a whole ``users.get`` batch produced no per-player outcome."""

    INVALID_TOKEN = "INVALID_TOKEN"  # codes 5, 27, 28 — CRITICAL once
    RETRY = "RETRY"                  # transport, HTTP 5xx, other codes


@dataclass(frozen=True)
class BatchResult:
    """
    Either one ``ProfileOutcome`` per requested id, or a batch-level
    ``failure`` (then ``outcomes`` is empty). ``error_code`` is the VK
    error code for logging — 0 for transport failures.
    """

    outcomes: dict[int, ProfileOutcome]
    failure: BatchFailure | None = None
    error_code: int = 0


class VkProfilesClient:
    """Thin async wrapper over ``users.get`` (Spec 3.4)."""

    def __init__(
        self,
        profiles: ProfilesConfig,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._photo_field = profiles.photo_field
        self._api_version = profiles.api_version
        self._bisect_pause_seconds = profiles.batch_pause_seconds
        self._client = httpx.AsyncClient(
            base_url=profiles.api_base_url,
            timeout=httpx.Timeout(profiles.http_timeout_seconds),
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
        )

    async def get_profiles(self, user_ids: list[int]) -> BatchResult:
        """One outcome per requested VK id, or a batch-level failure."""
        if not user_ids:
            return BatchResult(outcomes={})
        return await self._fetch(list(user_ids))

    async def _call(self, user_ids: list[int]) -> httpx.Response | None:
        """
        One POST ``/users.get``. Returns the response on any
        transportable answer (the body may still be an error envelope);
        ``None`` when nothing parseable could arrive — timeout,
        connection error, HTTP 5xx.
        """
        data = {
            "user_ids": ",".join(str(user_id) for user_id in user_ids),
            "fields": self._photo_field,
            "v": self._api_version,
        }
        try:
            response = await self._client.post("/users.get", data=data)
        except httpx.HTTPError as exc:
            logger.warning(
                "vk users.get failed: transport error (%s)",
                type(exc).__name__,
            )
            return None
        if response.status_code >= 500:
            logger.warning(
                "vk users.get failed: HTTP %s", response.status_code
            )
            return None
        return response

    async def _fetch(self, user_ids: list[int]) -> BatchResult:
        """One ``users.get`` call turned into a ``BatchResult``."""
        response = await self._call(user_ids)
        if response is None:
            return BatchResult(outcomes={}, failure=BatchFailure.RETRY)
        try:
            body = response.json()
        except ValueError:
            logger.warning(
                "vk users.get failed: non-JSON body (HTTP %s)",
                response.status_code,
            )
            return BatchResult(outcomes={}, failure=BatchFailure.RETRY)
        if not isinstance(body, dict):
            return BatchResult(outcomes={}, failure=BatchFailure.RETRY)

        call_error = body.get("error")
        if call_error is not None:
            code = (
                call_error.get("error_code")
                if isinstance(call_error, dict)
                else None
            )
            if not isinstance(code, int):
                return BatchResult(outcomes={}, failure=BatchFailure.RETRY)
            if code in _BISECT_ERROR_CODES:
                return await self._bisect(user_ids)
            if code in _INVALID_TOKEN_CODES:
                logger.warning(
                    "vk users.get call error: code %s", code
                )
                return BatchResult(
                    outcomes={},
                    failure=BatchFailure.INVALID_TOKEN,
                    error_code=code,
                )
            logger.warning("vk users.get call error: code %s", code)
            return BatchResult(
                outcomes={}, failure=BatchFailure.RETRY, error_code=code
            )

        entries = body.get("response")
        if not isinstance(entries, list):
            return BatchResult(outcomes={}, failure=BatchFailure.RETRY)
        by_id = {
            element.get("id"): element
            for element in entries
            if isinstance(element, dict)
        }
        outcomes: dict[int, ProfileOutcome] = {}
        for user_id in user_ids:
            element = by_id.get(user_id)
            if (
                element is None
                or "deactivated" in element
                or element.get("hidden") == 1
            ):
                outcomes[user_id] = ProfileOutcome(OutcomeKind.UNAVAILABLE)
                continue
            outcomes[user_id] = ProfileOutcome(
                OutcomeKind.OK,
                first_name=clean_name(element.get("first_name")),
                last_name=clean_name(element.get("last_name")),
                photo_url=clean_photo_url(element.get(self._photo_field)),
            )
        return BatchResult(outcomes=outcomes)

    async def _bisect(self, user_ids: list[int]) -> BatchResult:
        """
        Spec 3.4 for call errors 30/113 (one bad user in the batch):
        split the id list in half and re-request each half recursively;
        a single-id request resolves to ``UNAVAILABLE``. A batch-level
        failure of either half propagates unchanged.
        """
        if len(user_ids) == 1:
            return BatchResult(
                outcomes={
                    user_ids[0]: ProfileOutcome(OutcomeKind.UNAVAILABLE)
                }
            )
        middle = len(user_ids) // 2
        merged: dict[int, ProfileOutcome] = {}
        for half in (user_ids[:middle], user_ids[middle:]):
            if self._bisect_pause_seconds:
                await asyncio.sleep(self._bisect_pause_seconds)
            result = await self._fetch(half)
            if result.failure is not None:
                return result
            merged.update(result.outcomes)
        return BatchResult(outcomes=merged)

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
