"""
Tests for per-API-key usage tracking and daily quotas (issue #47)
"""

import asyncio
import json

import fakeredis
import httpx
import pytest
import respx

import config
from services import store, usage
from tests.conftest import GROQ_URL

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
CHAT_URL = GROQ_URL + "/chat/completions"
KEY_A = "key-a"
KEY_B = "key-b"
HDR_A = {"X-API-Key": KEY_A}
HDR_B = {"X-API-Key": KEY_B}
TRANSLATE_PAYLOAD = {"content": "Hello", "from_language": "en", "to_language": "yo"}


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", [KEY_A, KEY_B])


def azure_ok(text="Bawo ni"):
    return httpx.Response(200, json=[{"translations": [{"text": text}]}])


def llm_reply(prompt_tokens=50, completion_tokens=7):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


def sse_stream(*deltas, usage_chunk=None):
    lines = [f"data: {json.dumps({'choices': [{'delta': d}]})}\n\n" for d in deltas]
    if usage_chunk is not None:
        lines.append(f"data: {json.dumps({'choices': [{'delta': {}}], 'usage': usage_chunk})}\n\n")
    lines.append("data: [DONE]\n\n")
    return httpx.Response(
        200, content="".join(lines).encode(), headers={"content-type": "text/event-stream"}
    )


@respx.mock
def test_daily_quota_returns_429_for_the_limited_key(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY_QUOTAS", {KEY_A: 2})
    respx.post(TRANSLATE_URL).mock(return_value=azure_ok())

    first = client.post("/v1/translate", json=TRANSLATE_PAYLOAD, headers=HDR_A)
    second = client.post("/v1/translate", json=TRANSLATE_PAYLOAD, headers=HDR_A)
    third = client.post("/v1/translate", json=TRANSLATE_PAYLOAD, headers=HDR_A)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert "quota" in third.json()["message"].lower()
    assert int(third.headers["Retry-After"]) >= 1

    # The quota only applies to the configured key
    assert client.post("/v1/translate", json=TRANSLATE_PAYLOAD, headers=HDR_B).status_code == 200
    # Rejected requests do not consume extra quota
    assert client.post("/v1/translate", json=TRANSLATE_PAYLOAD, headers=HDR_A).status_code == 429


@respx.mock
def test_usage_endpoint_reports_counters_tokens_and_remaining(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEY_QUOTAS", {KEY_A: 10})
    respx.post(CHAT_URL).mock(return_value=llm_reply())

    client.post("/v1/chat", json={"message": "Hi", "language": "en"}, headers=HDR_A)
    response = client.get("/v1/usage", headers=HDR_A)

    assert response.status_code == 200
    data = response.json()
    assert data["quota"] == 10
    assert data["resets_at"] and data["resets_at"].endswith("Z")
    today = data["usage"][-1]
    assert today["date"] == usage.today()
    # The /v1/usage request itself is counted, so requests >= 2
    assert today["requests"] == 2
    assert today["upstream_calls"] == 1
    assert today["prompt_tokens"] == 50
    assert today["completion_tokens"] == 7
    assert today["total_tokens"] == 57
    assert data["remaining"] == 8


@respx.mock
def test_streaming_usage_is_captured_from_the_final_chunk(client, monkeypatch):
    respx.post(CHAT_URL).mock(
        return_value=sse_stream(
            {"content": "Hello"},
            usage_chunk={"prompt_tokens": 5, "completion_tokens": 3},
        )
    )

    response = client.post(
        "/v1/chat/stream", json={"message": "Hi", "language": "en"}, headers=HDR_A
    )

    assert response.status_code == 200
    stats = asyncio.run(usage.snapshot(usage.key_label(KEY_A)))
    assert stats.requests == 1
    assert stats.upstream_calls == 1
    assert stats.prompt_tokens == 5
    assert stats.completion_tokens == 3


def test_usage_endpoint_is_empty_without_api_keys(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", [])

    response = client.get("/v1/usage")

    assert response.status_code == 200
    assert response.json() == {
        "usage": [],
        "quota": None,
        "remaining": None,
        "resets_at": None,
    }


def test_metrics_use_hashed_key_labels(client, monkeypatch):
    label = usage.key_label(KEY_A)

    client.get("/v1/languages", headers=HDR_A)
    # Send a key: /metrics needs one when auth is configured (#87)
    metrics_text = client.get("/metrics", headers=HDR_A).text

    assert f'terngi_api_key_requests_total{{key="{label}"}}' in metrics_text
    assert KEY_A not in metrics_text
    assert KEY_B not in metrics_text


async def test_usage_is_shared_through_redis(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    store.set_redis(fake)
    redis_store = store.RedisStore("usage", config.USAGE_TTL_SECONDS)
    monkeypatch.setattr(usage, "usage_store", redis_store)
    try:
        # A "replica" writes counters
        assert (await usage.hit("label-a", quota=2))[0] is True
        assert (await usage.hit("label-a", quota=2))[0] is True
        blocked, usage_after = await usage.hit("label-a", quota=2)
        assert blocked is False
        assert usage_after.requests == 2
        usage.begin("label-a")
        await usage.record_upstream(prompt_tokens=4, completion_tokens=2)
        usage.begin(None)

        # A fresh store over the same Redis sees the same counters
        fresh = store.RedisStore("usage", config.USAGE_TTL_SECONDS)
        monkeypatch.setattr(usage, "usage_store", fresh)
        snapshot = await usage.snapshot("label-a")
        assert snapshot.requests == 2
        assert snapshot.upstream_calls == 1
        assert snapshot.total_tokens == 6
    finally:
        store.set_redis(None)
