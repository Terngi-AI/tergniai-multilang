"""
Tests for LLM translation/detection and the provider chain (Azure -> LLM providers)
"""

import json

import httpx
import pytest
import respx

import config
from tests.conftest import GROQ_URL

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
DETECT_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/detect"
CHAT_URL = GROQ_URL + "/chat/completions"


def chat_reply(payload) -> httpx.Response:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def chain(monkeypatch):
    """Translate and detect with Azure first, then Groq"""
    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["azure", "groq"])
    monkeypatch.setattr(config, "DETECTION_PROVIDERS", ["azure", "groq"])


def translate(client, content="Hello", src="en", tgt="yo"):
    return client.post(
        "/v1/translate", json={"content": content, "from_language": src, "to_language": tgt}
    )


@respx.mock
def test_llm_used_when_azure_not_configured(client, chain, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    route = respx.post(CHAT_URL).mock(return_value=chat_reply({"translations": ["Ẹ n lẹ"]}))

    response = translate(client)

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Ẹ n lẹ"
    body = json.loads(route.calls.last.request.content)
    assert "English to Yoruba" in body["messages"][0]["content"]
    assert body["response_format"] == {"type": "json_object"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-groq-key"


@respx.mock
def test_falls_back_to_llm_when_azure_fails(client, chain):
    azure = respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(500))
    llm = respx.post(CHAT_URL).mock(return_value=chat_reply({"translations": ["Ẹ n lẹ"]}))

    response = translate(client)

    assert response.json()["translated_text"] == "Ẹ n lẹ"
    assert azure.called and llm.called


@respx.mock
def test_azure_used_first_when_healthy(client, chain):
    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(200, json=[{"translations": [{"text": "Bawo ni"}]}])
    )
    llm = respx.post(CHAT_URL)

    assert translate(client).json()["translated_text"] == "Bawo ni"
    assert not llm.called


@respx.mock
def test_azure_only_chain_does_not_fall_back(client):
    respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(500))
    llm = respx.post(CHAT_URL)

    assert translate(client).status_code == 502
    assert not llm.called


def test_no_provider_configured_returns_503(client, chain, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    monkeypatch.setattr(config, "LLM_PROVIDERS", {})

    assert translate(client).status_code == 503
    ready = client.get("/health/ready").json()["services"]
    assert ready == {"translator": False, "llm": False, "agent": False}


@respx.mock
def test_llm_batch_translation(client, chain, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    route = respx.post(CHAT_URL).mock(
        return_value=chat_reply({"translations": ["Ụtụtụ ọma", "Daalụ"]})
    )

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["Good morning", "Thank you"], "from_language": "en", "to_language": "ig"},
    )

    assert response.json()["translations"] == ["Ụtụtụ ọma", "Daalụ"]
    sent = json.loads(json.loads(route.calls.last.request.content)["messages"][1]["content"])
    assert sent == {"texts": ["Good morning", "Thank you"]}


@respx.mock
@pytest.mark.parametrize(
    "reply",
    [
        {"translations": ["only one"]},
        {"translations": "not a list"},
        {"wrong_key": []},
        "not json at all",
    ],
)
def test_bad_llm_translation_output_returns_502(client, chain, monkeypatch, reply):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    respx.post(CHAT_URL).mock(return_value=chat_reply(reply))

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["a", "b"], "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 502


@respx.mock
def test_json_in_code_fence_is_accepted(client, chain, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    respx.post(CHAT_URL).mock(return_value=chat_reply('```json\n{"translations": ["Sannu"]}\n```'))

    assert translate(client, tgt="ha").json()["translated_text"] == "Sannu"


@respx.mock
def test_detect_falls_back_to_llm(client, chain):
    respx.post(DETECT_URL).mock(return_value=httpx.Response(401))
    respx.post(CHAT_URL).mock(return_value=chat_reply({"language": "HA", "score": 0.93}))

    response = client.post("/v1/detect", json={"content": "Ina kwana?"})

    assert response.status_code == 200
    assert response.json() == {
        "language": "ha",
        "language_name": "Hausa",
        "score": 0.93,
        "is_supported": True,
    }


@respx.mock
def test_llm_detect_clamps_bad_score(client, chain, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    respx.post(CHAT_URL).mock(return_value=chat_reply({"language": "yo", "score": "very sure"}))

    assert client.post("/v1/detect", json={"content": "Bawo ni"}).json()["score"] == 0.0


@respx.mock
def test_pidgin_translation(client, chain, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    route = respx.post(CHAT_URL).mock(
        return_value=chat_reply({"translations": ["You dey go where?"]})
    )

    response = translate(client, content="Where are you going?", tgt="pcm")

    assert response.json()["translated_text"] == "You dey go where?"
    assert (
        "Nigerian Pidgin" in json.loads(route.calls.last.request.content)["messages"][0]["content"]
    )


@respx.mock
def test_azure_skipped_for_languages_it_does_not_support(client, chain):
    azure = respx.post(TRANSLATE_URL)
    respx.post(CHAT_URL).mock(return_value=chat_reply({"translations": ["Sawubona"]}))

    response = translate(client, content="Hello", tgt="nr")

    assert response.json()["translated_text"] == "Sawubona"
    assert not azure.called


@respx.mock
def test_azure_used_for_new_supported_languages(client, chain):
    azure = respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(200, json=[{"translations": [{"text": "Habari"}]}])
    )

    assert translate(client, tgt="sw").json()["translated_text"] == "Habari"
    assert azure.called


@respx.mock
@pytest.mark.parametrize(
    ("detected", "expected"),
    [("zh-hans", "zh-Hans"), ("zh", "zh-Hans"), ("ZH-TW", "zh-Hant"), ("no", "nb"), ("tl", "fil")],
)
def test_detected_codes_are_normalised(client, chain, monkeypatch, detected, expected):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    respx.post(CHAT_URL).mock(return_value=chat_reply({"language": detected, "score": 0.9}))

    body = client.post("/v1/detect", json={"content": "text"}).json()

    assert body["language"] == expected
    assert body["is_supported"] is True
