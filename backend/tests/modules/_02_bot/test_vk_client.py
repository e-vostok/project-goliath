"""
Tests for VkClient (Spec 3.3, Appendix T: T22; INV-B9).

The VK boundary is a scripted ``httpx.MockTransport`` (FakeVk).
Coverage: success ``response[0].message_id``, recipient error
``response[0].error.code``, top-level call ``error.error_code``,
every transport-failure shape (empty list, neither field, not JSON,
HTTP 5xx, timeout, connection error), the Authorization header and
parameter contract (no ``intent``, ``v`` pinned, mentions/links
disabled), and ``isMessagesFromGroupAllowed`` 1/0/None.
"""

from __future__ import annotations

import pytest
from urllib.parse import parse_qs

import httpx

from modules._02_bot.vk_client import SendKind, VkClient
from tests.fixtures.fake_vk import FakeVk

TOKEN = "unit-test-token-not-real"
GROUP_ID = "12345"


def _client(bot_config, fake: FakeVk) -> VkClient:
    return VkClient(bot_config, TOKEN, GROUP_ID, transport=fake.transport)


class TestSendMessage:
    async def test_success_and_request_contract(self, bot_config):
        fake = FakeVk()
        fake.respond_send_ok(message_id=77)
        outcome = await _client(bot_config, fake).send_message(
            peer_id=555, random_id=42, message="hi", keyboard_json='{"a":1}'
        )
        assert outcome.kind == SendKind.OK
        assert outcome.message_id == 77
        assert outcome.code == 0

        request = fake.requests[0]
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(request.url)
        form = parse_qs(request.content.decode())
        form = {k: v[0] for k, v in form.items()}
        assert form["peer_ids"] == "555"
        assert form["random_id"] == "42"
        assert form["message"] == "hi"
        assert form["keyboard"] == '{"a":1}'
        assert form["disable_mentions"] == "1"
        assert form["dont_parse_links"] == "1"
        assert form["v"] == bot_config.vk.api_version
        assert "intent" not in form

    async def test_recipient_error(self, bot_config):
        fake = FakeVk()
        fake.respond_recipient_error(901)
        outcome = await _client(bot_config, fake).send_message(
            peer_id=1, random_id=1, message="x"
        )
        assert outcome.kind == SendKind.ERROR
        assert outcome.code == 901
        assert outcome.message_id is None

    async def test_call_error(self, bot_config):
        fake = FakeVk()
        fake.respond_call_error(5)
        outcome = await _client(bot_config, fake).send_message(
            peer_id=1, random_id=1, message="x"
        )
        assert outcome.kind == SendKind.ERROR
        assert outcome.code == 5

    @pytest.mark.parametrize(
        "script",
        [
            "empty_list",
            "neither_field",
            "not_json",
            "http_500",
            "timeout",
            "connect_error",
            "error_string",
        ],
    )
    async def test_transport_failures(self, bot_config, script):
        fake = FakeVk()
        if script == "empty_list":
            fake.respond_json({"response": []})
        elif script == "neither_field":
            fake.respond_json({"response": [{"peer_id": 1}]})
        elif script == "not_json":
            fake.respond_raw("<html>oops</html>")
        elif script == "http_500":
            fake.respond_raw("server error", status=500)
        elif script == "timeout":
            fake.fail_timeout()
        elif script == "connect_error":
            fake.fail_connect()
        elif script == "error_string":
            fake.respond_json(
                {"response": [{"peer_id": 1, "error": "oops"}]}
            )
        outcome = await _client(bot_config, fake).send_message(
            peer_id=1, random_id=1, message="x"
        )
        assert outcome.kind == SendKind.TRANSPORT
        assert outcome.code == 0

    async def test_no_keyboard_param_when_absent(self, bot_config):
        fake = FakeVk()
        fake.respond_send_ok()
        await _client(bot_config, fake).send_message(
            peer_id=1, random_id=1, message="x", keyboard_json=None
        )
        form = parse_qs(fake.requests[0].content.decode())
        assert "keyboard" not in form

    async def test_token_never_in_url_logs_or_exceptions(
        self, bot_config, caplog
    ):
        """INV-B9: the key travels only in the Authorization header."""
        fake = FakeVk()
        fake.fail_timeout()
        with caplog.at_level("WARNING"):
            outcome = await _client(bot_config, fake).send_message(
                peer_id=1, random_id=1, message="x"
            )
        assert outcome.kind == SendKind.TRANSPORT
        for record in caplog.records:
            assert TOKEN not in record.getMessage()
        assert TOKEN not in str(fake.requests[0].url)


class TestIsMessagesFromGroupAllowed:
    async def test_allowed_and_denied(self, bot_config):
        fake = FakeVk()
        fake.respond_allowed(True)
        client = _client(bot_config, fake)
        assert await client.is_messages_from_group_allowed(12345, 7) is True
        fake.respond_allowed(False)
        assert await client.is_messages_from_group_allowed(12345, 7) is False
        form = parse_qs(fake.requests[-1].content.decode())
        assert form["group_id"] == ["12345"]
        assert form["user_id"] == ["7"]

    @pytest.mark.parametrize(
        "script", ["call_error", "malformed", "timeout"]
    )
    async def test_none_on_failure(self, bot_config, script):
        fake = FakeVk()
        if script == "call_error":
            fake.respond_call_error(10)
        elif script == "malformed":
            fake.respond_json({"response": "nope"})
        else:
            fake.fail_timeout()
        client = _client(bot_config, fake)
        assert (
            await client.is_messages_from_group_allowed(12345, 7) is None
        )


async def test_aclose(bot_config):
    fake = FakeVk()
    client = _client(bot_config, fake)
    await client.aclose()
    with pytest.raises(RuntimeError):
        await client.send_message(peer_id=1, random_id=1, message="x")
