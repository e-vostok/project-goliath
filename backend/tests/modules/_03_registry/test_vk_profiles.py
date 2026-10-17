"""
Tests for the ``users.get`` client of 03_registry (Spec 3.4).

No database here — the VK boundary is the scripted ``FakeVk``
(httpx.MockTransport); the client turns each response into one
outcome per requested id, or a batch-level failure.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from modules._03_registry.config_schema import RegistryConfig
from modules._03_registry.vk_profiles import (
    BatchFailure,
    OutcomeKind,
    ProfileOutcome,
    VkProfilesClient,
    clean_name,
    clean_photo_url,
)
from tests.fixtures.fake_vk import FakeVk

PROFILES = RegistryConfig.from_yaml(RegistryConfig.get_default_config_path()).profiles
# Bisect tests must not wait on the configured inter-call pause.
FAST_PROFILES = PROFILES.model_copy(update={"batch_pause_seconds": 0})
TEST_TOKEN = "test-group-token-SECRET"


def make_client(fake: FakeVk, profiles=PROFILES) -> VkProfilesClient:
    return VkProfilesClient(profiles, TEST_TOKEN, transport=fake.transport)


class TestGetProfiles:
    """Response parsing — one outcome per requested id (Spec 3.4)."""

    async def test_ok_unavailable_and_captured_request(self):
        fake = FakeVk()
        fake.respond_users_get(
            [
                {
                    "id": 11,
                    "first_name": "Иван",
                    "last_name": "Петров",
                    "photo_50": "https://sun9-west.userapi.com/a.png",
                },
                {
                    "id": 22,
                    "first_name": "Мария",
                    "last_name": "Смирнова",
                    "photo_50": "https://vk.com/images/camera_50.png",
                },
                {"id": 33, "first_name": "DELETED", "deactivated": "banned"},
                {"id": 44, "first_name": "Скрытый", "hidden": 1},
            ]
        )
        client = make_client(fake)

        result = await client.get_profiles([11, 22, 33, 44, 55])

        assert result.failure is None
        assert result.outcomes[11] == ProfileOutcome(
            OutcomeKind.OK,
            first_name="Иван",
            last_name="Петров",
            photo_url="https://sun9-west.userapi.com/a.png",
        )
        # The camera stub means "no photo" — stored as None.
        assert result.outcomes[22].photo_url is None
        assert result.outcomes[33].kind is OutcomeKind.UNAVAILABLE
        assert result.outcomes[44].kind is OutcomeKind.UNAVAILABLE
        # A requested id missing from the response is UNAVAILABLE.
        assert result.outcomes[55].kind is OutcomeKind.UNAVAILABLE

        # One captured users.get request — the report masks the key.
        request = fake.users_get_requests()[0]
        assert request.method == "POST"
        assert request.url.path == "/method/users.get"
        assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
        assert fake.form_of(request) == {
            "user_ids": "11,22,33,44,55",
            "fields": "photo_50",
            "v": "5.199",
        }

    async def test_bisect_error_30_then_halves_succeed(self):
        """Error 30 names one bad id: the batch splits, the bad id in a
        half resolves to UNAVAILABLE (Spec 3.4)."""
        fake = FakeVk()
        fake.respond_call_error(30)
        fake.respond_users_get([{"id": 11, "first_name": "А", "last_name": "Б"}])
        fake.respond_users_get([{"id": 33, "first_name": "В", "last_name": "Г"}])
        client = make_client(fake, profiles=FAST_PROFILES)

        result = await client.get_profiles([11, 22, 33])

        assert result.failure is None
        assert result.outcomes[11].kind is OutcomeKind.OK
        assert result.outcomes[22].kind is OutcomeKind.UNAVAILABLE
        assert result.outcomes[33].kind is OutcomeKind.OK
        forms = [fake.form_of(r) for r in fake.users_get_requests()]
        assert [f["user_ids"] for f in forms] == ["11,22,33", "11", "22,33"]

    async def test_bisect_error_113_single_id_unavailable(self):
        """A single-id request hitting 113 resolves to UNAVAILABLE —
        no infinite recursion (Spec 3.4)."""
        fake = FakeVk()
        fake.respond_call_error(113)
        client = make_client(fake, profiles=FAST_PROFILES)

        result = await client.get_profiles([77])

        assert result.failure is None
        assert result.outcomes == {77: ProfileOutcome(OutcomeKind.UNAVAILABLE)}
        assert len(fake.users_get_requests()) == 1

    @pytest.mark.parametrize("code", [5, 27, 28])
    async def test_invalid_token_codes(self, code):
        """Codes 5/27/28 — the key is dead: an INVALID_TOKEN batch
        failure (Spec 3.4, R6)."""
        fake = FakeVk()
        fake.respond_call_error(code)
        client = make_client(fake)

        result = await client.get_profiles([11, 22])

        assert result.failure is BatchFailure.INVALID_TOKEN
        assert result.error_code == code
        assert result.outcomes == {}

    async def test_transport_5xx_and_other_codes_retry(self):
        """Network error, HTTP 5xx and other error codes — a plain
        RETRY batch failure (Spec 3.4)."""
        fake = FakeVk()
        client = make_client(fake)

        fake.fail_connect()
        assert (await client.get_profiles([11])).failure is BatchFailure.RETRY

        fake.push(httpx.Response(503, content=b"gateway"))
        assert (await client.get_profiles([11])).failure is BatchFailure.RETRY

        fake.respond_call_error(6)
        result = await client.get_profiles([11])
        assert result.failure is BatchFailure.RETRY
        assert result.error_code == 6


class TestSanitising:
    """Spec 3.4 cleaning — pure functions, no VK call."""

    def test_names(self):
        assert clean_name("  Ив\x00ан\n") == "Иван"
        assert clean_name("x" * 100) == "x" * 64
        assert clean_name("\x00\x1f") is None
        assert clean_name(None) is None
        assert clean_name(42) is None

    def test_photo_urls(self):
        assert clean_photo_url("http://insecure.ru/a.png") is None
        assert clean_photo_url("https://vk.com/images/camera_50.png") is None
        assert clean_photo_url("https://vk.com/images/camera_100.png") is None
        assert clean_photo_url("https://" + "x" * 1100) is None
        assert clean_photo_url(None) is None
        good = "https://sun9-west.userapi.com/impf/abc.jpg"
        assert clean_photo_url(good) == good


class TestTokenSafety:
    """The community key travels only in the Authorization header."""

    async def test_token_never_in_logs_or_repr(self, caplog):
        fake = FakeVk()
        fake.respond_call_error(5)  # even an auth failure stays silent
        client = make_client(fake)
        with caplog.at_level(logging.DEBUG):
            await client.get_profiles([11])

        blob = "\n".join(record.getMessage() for record in caplog.records)
        assert TEST_TOKEN not in blob
        assert TEST_TOKEN not in repr(client)
        request = fake.users_get_requests()[0]
        assert request.headers["authorization"] == f"Bearer {TEST_TOKEN}"
        assert TEST_TOKEN not in str(request.url)
        assert TEST_TOKEN not in request.content.decode()
