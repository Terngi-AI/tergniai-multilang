"""
Tests for Groq translation/detection and the Azure -> Groq fallback
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from fastapi import HTTPException

import config
from services import groq_service

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
DETECT_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/detect"


@pytest.fixture
def groq(monkeypatch):
    """Fake Groq client; set `groq.reply` to the JSON object the model returns"""
    create = AsyncMock()
    client = MagicMock()
    client.chat.completions.create = create

    def reply(payload):
        content = payload if isinstance(payload, str) else json.dumps(payload)
        create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    create.reply = reply
    monkeypatch.setattr(groq_service, "get_client", lambda: client)
    monkeypatch.setattr(config, "TRANSLATION_PROVIDER", "auto")
    return create


def translate(client, content="Hello", src="en", tgt="yo"):
    return client.post(
        "/v1/translate", json={"content": content, "from_language": src, "to_language": tgt}
    )


def test_groq_used_when_azure_not_configured(client, groq, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEY", "")
    groq.reply({"translations": ["Ẹ n lẹ"]})

    response = translate(client)

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Ẹ n lẹ"
    prompt = groq.await_args.kwargs["messages"][0]["content"]
    assert "English to Yoruba" in prompt
    assert groq.await_args.kwargs["response_format"] == {"type": "json_object"}


@respx.mock
def test_falls_back_to_groq_when_azure_fails(client, groq):
    azure = respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(401, text="revoked"))
    groq.reply({"translations": ["Ẹ n lẹ"]})

    response = translate(client)

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Ẹ n lẹ"
    assert azure.called
    assert groq.await_count == 1


@respx.mock
def test_azure_used_first_when_healthy(client, groq):
    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(200, json=[{"translations": [{"text": "Bawo ni"}]}])
    )

    response = translate(client)

    assert response.json()["translated_text"] == "Bawo ni"
    assert groq.await_count == 0


@respx.mock
def test_azure_only_mode_does_not_fall_back(client, groq, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_PROVIDER", "azure")
    respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(500))

    response = translate(client)

    assert response.status_code == 502
    assert groq.await_count == 0


def test_groq_only_mode(client, groq, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_PROVIDER", "groq")
    groq.reply({"translations": ["Sannu"]})

    response = translate(client, tgt="ha")

    assert response.json()["translated_text"] == "Sannu"


def test_no_provider_configured_returns_503(client, groq, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")

    response = translate(client)

    assert response.status_code == 503
    assert client.get("/health/ready").json()["services"]["translator"] is False


def test_groq_batch_translation(client, groq, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEY", "")
    groq.reply({"translations": ["Ụtụtụ ọma", "Daalụ"]})

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["Good morning", "Thank you"], "from_language": "en", "to_language": "ig"},
    )

    assert response.json()["translations"] == ["Ụtụtụ ọma", "Daalụ"]
    sent = json.loads(groq.await_args.kwargs["messages"][1]["content"])
    assert sent == {"texts": ["Good morning", "Thank you"]}


@pytest.mark.parametrize(
    "reply",
    [
        {"translations": ["only one"]},
        {"translations": "not a list"},
        {"wrong_key": []},
        "not json at all",
    ],
)
def test_groq_bad_translation_output_returns_502(client, groq, monkeypatch, reply):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEY", "")
    groq.reply(reply)

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["a", "b"], "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 502


@respx.mock
def test_detect_falls_back_to_groq(client, groq):
    respx.post(DETECT_URL).mock(return_value=httpx.Response(401))
    groq.reply({"language": "HA", "score": 0.93})

    response = client.post("/v1/detect", json={"content": "Ina kwana?"})

    assert response.status_code == 200
    assert response.json() == {
        "language": "ha",
        "language_name": "Hausa",
        "score": 0.93,
        "is_supported": True,
    }


@pytest.mark.asyncio
async def test_groq_detect_clamps_bad_score(groq):
    groq.reply({"language": "yo", "score": "very sure"})

    assert await groq_service.detect_language("Bawo ni") == ("yo", 0.0)


@pytest.mark.asyncio
async def test_groq_detect_requires_language(groq):
    groq.reply({"score": 0.5})

    with pytest.raises(HTTPException) as exc_info:
        await groq_service.detect_language("???")

    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_groq_api_error_returns_502(groq):
    groq.side_effect = RuntimeError("boom")

    with pytest.raises(HTTPException) as exc_info:
        await groq_service.translate_batch(["hi"], "en", "yo")

    assert exc_info.value.status_code == 502
