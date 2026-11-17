"""
Tests for request deadlines and the global upstream-attempt cap
"""

import asyncio

import httpx
import pytest
import respx
from fastapi import HTTPException

import config
import middleware
from services import deadline, translator, whatsapp

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
GROQ_URL = "https://api.groq.com/openai/v1"
PAYLOAD = {"content": "deadline test", "from_language": "en", "to_language": "fr"}


def test_request_deadline_returns_504_with_retry_after(client, monkeypatch):
    async def slow_translation(*args, **kwargs):
        await asyncio.sleep(0.2)
        return ["texte traduit"]

    monkeypatch.setattr(config, "REQUEST_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(translator.azure_translator, "translate_batch", slow_translation)

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 504
    assert response.headers["Retry-After"] == "1"
    assert response.json()["code"] == "gateway_timeout"


@respx.mock
def test_fallbacks_share_the_request_deadline(client, monkeypatch):
    async def slow_translation(*args, **kwargs):
        await asyncio.sleep(0.2)
        return ["texte traduit"]

    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["azure", "groq"])
    monkeypatch.setattr(config, "REQUEST_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(translator.azure_translator, "translate_batch", slow_translation)
    fallback = respx.post(GROQ_URL + "/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "late"}}]})
    )

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 504
    assert fallback.call_count == 0


@respx.mock
def test_global_attempt_cap_returns_503_with_retry_after(client, monkeypatch):
    route = respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(500))
    monkeypatch.setattr(config, "UPSTREAM_MAX_RETRIES", 10)
    monkeypatch.setattr(config, "REQUEST_MAX_UPSTREAM_ATTEMPTS", 2)

    response = client.post("/v1/translate", json=PAYLOAD)

    assert route.call_count == 2
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["code"] == "service_unavailable"


def test_attempt_budget_is_shared_across_providers(monkeypatch):
    monkeypatch.setattr(config, "REQUEST_MAX_UPSTREAM_ATTEMPTS", 2)
    tokens = deadline.begin(10)

    try:
        deadline.consume_attempt()
        deadline.consume_attempt()
        assert deadline.attempts_used() == 2
        with pytest.raises(HTTPException) as error:
            deadline.consume_attempt()
    finally:
        deadline.end(tokens)

    assert error.value.status_code == 503
    assert error.value.headers["Retry-After"] == "5"


def test_timeout_never_exceeds_the_request_deadline():
    tokens = deadline.begin(0.5)

    try:
        assert deadline.timeout(30) <= 0.5
    finally:
        deadline.end(tokens)


async def test_whatsapp_webhook_is_not_cut_by_the_request_deadline(monkeypatch):
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.sleep(0.1)
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    monkeypatch.setattr(config, "REQUEST_DEADLINE_SECONDS", 0.02)

    await middleware.DeadlineMiddleware(app)(
        {"type": "http", "path": "/v1/whatsapp/webhook", "scheme": "http", "state": {}},
        receive,
        send,
    )

    assert messages[-1]["type"] == "http.response.body"
    assert messages[-1]["body"] == b"ok"


async def test_whatsapp_delivery_starts_its_own_deadline(monkeypatch):
    sent = []

    async def fake_reply_to(message):
        deadline.check()  # the webhook's deadline has long expired
        return "Hello!"

    async def fake_send_text(to, text):
        deadline.check()
        sent.append((to, text))
        return ["wamid.out1"]

    monkeypatch.setattr(whatsapp, "reply_to", fake_reply_to)
    monkeypatch.setattr(whatsapp, "send_text", fake_send_text)
    monkeypatch.setattr(config, "REQUEST_DEADLINE_SECONDS", 5)

    tokens = deadline.begin(0.01)
    await asyncio.sleep(0.02)
    try:
        await whatsapp.handle({"from": "2348012345678", "id": "wamid.in1"})
    finally:
        deadline.end(tokens)

    assert sent == [("2348012345678", "Hello!")]
