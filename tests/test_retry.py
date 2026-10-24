"""
Tests for retrying upstream calls with exponential backoff
"""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import List

import httpx
import pytest
import respx
from fastapi import HTTPException

import config
from services import assistant, azure_translator, retry

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PAYLOAD = {"content": "Hello", "from_language": "en", "to_language": "yo"}


def azure_ok(text: str = "Bawo ni") -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": text, "to": "yo"}]}])


@pytest.fixture
def sleeps(monkeypatch) -> List[float]:
    """Record backoff delays instead of actually sleeping"""
    recorded: List[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr("services.deadline.sleep", fake_sleep)
    monkeypatch.setattr(config, "UPSTREAM_MAX_RETRIES", 2)
    monkeypatch.setattr(config, "UPSTREAM_RETRY_BASE_DELAY", 0.5)
    monkeypatch.setattr(config, "UPSTREAM_RETRY_MAX_DELAY", 10.0)
    return recorded


@respx.mock
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_azure_retries_transient_status_then_succeeds(client, sleeps, status):
    route = respx.post(TRANSLATE_URL).mock(side_effect=[httpx.Response(status), azure_ok()])

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Bawo ni"
    assert route.call_count == 2
    assert len(sleeps) == 1


@respx.mock
def test_azure_retries_connection_error_then_succeeds(client, sleeps):
    route = respx.post(TRANSLATE_URL).mock(side_effect=[httpx.ConnectError("refused"), azure_ok()])

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
def test_azure_retry_exhaustion_returns_502(client, sleeps):
    route = respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(503, text="busy"))

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 502
    assert "busy" not in response.text
    assert route.call_count == 3  # first try + 2 retries
    assert len(sleeps) == 2


@respx.mock
def test_azure_connection_error_exhaustion_returns_502(client, sleeps):
    route = respx.post(TRANSLATE_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 502
    assert route.call_count == 3


@respx.mock
@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_azure_does_not_retry_client_errors(client, sleeps, status):
    route = respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(status))

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 502
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_azure_retries_disabled(client, sleeps, monkeypatch):
    monkeypatch.setattr(config, "UPSTREAM_MAX_RETRIES", 0)
    route = respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(503))

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 502
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_azure_honours_retry_after_seconds(client, sleeps):
    respx.post(TRANSLATE_URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1.5"}), azure_ok()]
    )

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 200
    assert sleeps == [1.5]


@respx.mock
def test_azure_honours_retry_after_http_date(client, sleeps):
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=3), usegmt=True)
    respx.post(TRANSLATE_URL).mock(
        side_effect=[httpx.Response(503, headers={"Retry-After": when}), azure_ok()]
    )

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 200
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 3


@respx.mock
def test_azure_retry_after_above_cap_fails_fast(client, sleeps):
    route = respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3600"})
    )

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 502
    assert route.call_count == 1
    assert sleeps == []


def test_backoff_jitter_stays_within_ceiling(sleeps):
    for _ in range(50):
        delay = azure_translator._retry_delay(2, None)
        assert delay is not None and 0 <= delay <= 2.0


def test_backoff_ceiling_doubles_and_is_capped(sleeps, monkeypatch):
    # Pin jitter to its upper bound to check the ceiling at each attempt
    monkeypatch.setattr(retry.random, "uniform", lambda low, high: high)
    ceilings = [azure_translator._retry_delay(n, None) for n in range(7)]
    assert ceilings == [0.5, 1.0, 2.0, 4.0, 8.0, 10.0, 10.0]


@pytest.mark.parametrize(
    ("header", "expected"),
    [("2", 2.0), ("0", 0.0), ("-5", 0.0), ("soon", None), ("", None), (None, None)],
)
def test_parse_retry_after(header, expected):
    assert azure_translator._parse_retry_after(header) == expected


def test_parse_retry_after_past_date_is_zero():
    past = format_datetime(datetime.now(UTC) - timedelta(minutes=5), usegmt=True)
    assert azure_translator._parse_retry_after(past) == 0.0


def groq_ok(reply: str = "Hello!") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})


@respx.mock
async def test_llm_retries_transient_error_then_succeeds(sleeps):
    route = respx.post(GROQ_URL).mock(side_effect=[httpx.Response(503), groq_ok()])

    assert await assistant.get_response("Hi") == "Hello!"
    assert route.call_count == 2
    assert len(sleeps) == 1


@respx.mock
async def test_llm_retry_exhaustion_returns_502(sleeps, monkeypatch):
    monkeypatch.setattr(config, "UPSTREAM_MAX_RETRIES", 1)
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(HTTPException) as exc:
        await assistant.get_response("Hi")

    assert exc.value.status_code == 502
    assert route.call_count == 2  # first try + 1 retry


@respx.mock
async def test_llm_rate_limit_is_not_retried_in_place(sleeps):
    # 429s are handled by rotating keys and models, not by sleeping on the same one
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(429))

    with pytest.raises(HTTPException):
        await assistant.get_response("Hi")

    assert route.call_count == 1
    assert sleeps == []


@respx.mock
async def test_llm_client_errors_are_not_retried(sleeps):
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(400))

    with pytest.raises(HTTPException):
        await assistant.get_response("Hi")

    assert route.call_count == 1
