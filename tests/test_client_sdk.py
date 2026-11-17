"""
Tests for the Python SDK in clients/python, run against the real app (upstream services
mocked), so the client can't drift from the API's actual paths and fields
"""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from terngi import (
    APIResponseError,
    AuthenticationError,
    ChatResponse,
    Message,
    RateLimitError,
    TerngiClient,
)

import config
import middleware
from main import app
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"
TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
DETECT_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/detect"


def answer(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.fixture
def sdk():
    with TerngiClient(http_client=TestClient(app)) as client:
        yield client


@respx.mock
def test_chat_remembers_the_conversation(sdk):
    respx.post(CHAT_URL).mock(side_effect=[answer("Hello Ada!"), answer("You're Ada.")])

    first = sdk.chat("I'm Ada", language="en")
    second = sdk.chat("Who am I?", conversation_id=first.conversation_id, language="en")

    assert isinstance(first, ChatResponse)
    assert first.reply == "Hello Ada!"
    assert second.reply == "You're Ada."
    history = sdk.get_conversation(first.conversation_id)
    assert [m.content for m in history.messages] == [
        "I'm Ada",
        "Hello Ada!",
        "Who am I?",
        "You're Ada.",
    ]

    sdk.delete_conversation(first.conversation_id)
    with pytest.raises(APIResponseError) as exc:
        sdk.get_conversation(first.conversation_id)
    assert exc.value.status_code == 404
    assert exc.value.message == "Conversation not found or expired"


def sse(*deltas) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': d}]})}\n\n" for d in deltas]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


@respx.mock
def test_chat_stream_yields_events(sdk):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, content=sse({"content": "Hi"}, {"content": " there"}))
    )

    events = list(sdk.chat_stream("Hello", language="en"))

    assert [e.event for e in events] == ["start", "token", "token", "done"]
    assert "".join(e.data["text"] for e in events if e.event == "token") == "Hi there"
    assert events[-1].data["reply"] == "Hi there"


@respx.mock
def test_translate_and_batch(sdk):
    respx.post(TRANSLATE_URL).mock(
        side_effect=[
            httpx.Response(200, json=[{"translations": [{"text": "Bawo ni"}]}]),
            httpx.Response(
                200,
                json=[
                    {"translations": [{"text": "Na gode"}]},
                    {"translations": [{"text": "Sai da safe"}]},
                ],
            ),
        ]
    )

    single = sdk.translate("Hello", to_language="yo", from_language="en")
    batch = sdk.translate_batch(["Thank you", "Good night"], to_language="ha", from_language="en")

    assert single.translated_text == "Bawo ni"
    assert single.original_text == "Hello"
    assert batch.translations == ["Na gode", "Sai da safe"]


@respx.mock
def test_detect(sdk):
    respx.post(DETECT_URL).mock(
        return_value=httpx.Response(200, json=[{"language": "sw", "score": 0.97}])
    )

    detected = sdk.detect("Habari yako?")

    assert detected.language == "sw"
    assert detected.language_name == "Swahili"
    assert detected.score == 0.97
    assert detected.is_supported is True


@respx.mock
def test_agent_with_history(sdk):
    route = respx.post(CHAT_URL).mock(return_value=answer("Your name is Ada."))

    reply = sdk.agent(
        "What's my name?",
        language="en",
        history=[
            Message(role="user", content="I'm Ada"),
            Message(role="assistant", content="Hi Ada"),
        ],
    )

    assert reply.answer == "Your name is Ada."
    sent = json.loads(route.calls.last.request.content)["messages"]
    assert [m["content"] for m in sent[1:3]] == ["I'm Ada", "Hi Ada"]


def test_languages(sdk):
    languages = sdk.languages()

    assert languages["yo"] == "Yoruba"
    assert len(languages) > 80


def test_api_key_is_sent_as_x_api_key(monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    with TerngiClient(api_key="wrong", http_client=TestClient(app)) as bad:
        with pytest.raises(AuthenticationError) as exc:
            bad.translate("Hi", to_language="en", from_language="en")
    assert exc.value.status_code == 401

    with TerngiClient(api_key="secret", http_client=TestClient(app)) as good:
        assert good.translate("Hi", to_language="en", from_language="en").translated_text == "Hi"


def test_rate_limit_error_has_retry_after(sdk, monkeypatch):
    monkeypatch.setattr(middleware.rate_limiter, "limit", 1)

    sdk.translate("Hi", to_language="en", from_language="en")
    with pytest.raises(RateLimitError) as exc:
        sdk.translate("Hi", to_language="en", from_language="en")

    assert exc.value.status_code == 429
    assert exc.value.retry_after is not None and exc.value.retry_after >= 1


def test_validation_errors_are_reported(sdk):
    with pytest.raises(APIResponseError) as exc:
        sdk.translate("Hi", to_language="klingon")

    assert exc.value.status_code == 400


def test_injected_http_client_is_not_closed():
    http = TestClient(app)
    with TerngiClient(http_client=http):
        pass

    assert http.get("/health").status_code == 200


def test_owned_client_uses_base_url_and_headers():
    client = TerngiClient(api_key="k", base_url="https://api.example.com/")

    assert str(client._client.base_url) == "https://api.example.com"
    assert client._client.headers["X-API-Key"] == "k"
    assert client._client.headers["User-Agent"].startswith("terngi-python-sdk/")
    client.close()
    assert client._client.is_closed
