"""Tests for glossary-aware translation (issue #42)"""

import json

import httpx
import respx

import config
from services import assistant
from tests.conftest import GROQ_URL

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
CHAT_URL = GROQ_URL + "/chat/completions"
MORENA_URL = "http://localhost:8080"


def azure_ok(text: str) -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": text, "to": "yo"}]}])


def chat_reply(text: str) -> httpx.Response:
    if isinstance(text, dict):
        text = json.dumps(text, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def sent_text(route) -> str:
    return json.loads(route.calls.last.request.content)[0]["text"]


@respx.mock
def test_azure_uses_dynamic_dictionary_for_protected_terms(client):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_ok("Kaabo si Terngi"))

    response = client.post(
        "/v1/translate",
        json={
            "content": "Welcome to Terngi",
            "from_language": "en",
            "to_language": "yo",
            "glossary": {"Terngi": "Terngi"},
        },
    )

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Kaabo si Terngi"
    assert '<mstrans:dictionary translation="Terngi">Terngi</mstrans:dictionary>' in sent_text(
        route
    )


@respx.mock
def test_azure_uses_the_entry_for_the_target_language(client):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_ok("Ina son kudin waya"))

    response = client.post(
        "/v1/translate",
        json={
            "content": "I like mobile money",
            "from_language": "en",
            "to_language": "ha",
            "glossary": {"mobile money": {"ha": "kudin waya", "yo": "owo alagbeka"}},
        },
    )

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Ina son kudin waya"
    assert (
        '<mstrans:dictionary translation="kudin waya">mobile money</mstrans:dictionary>'
        in sent_text(route)
    )


@respx.mock
def test_azure_ignores_entries_for_other_target_languages(client):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_ok("Bawo ni"))

    response = client.post(
        "/v1/translate",
        json={
            "content": "Hello",
            "from_language": "en",
            "to_language": "yo",
            "glossary": {"mobile money": {"ha": "kudin waya"}},
        },
    )

    assert response.status_code == 200
    assert sent_text(route) == "Hello"


@respx.mock
def test_llm_prompt_contains_the_glossary(client, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["groq"])
    route = respx.post(CHAT_URL).mock(
        return_value=chat_reply({"translations": ["Ẹ kú àárọ̀ Terngi"]})
    )

    response = client.post(
        "/v1/translate",
        json={
            "content": "Good morning Terngi",
            "from_language": "en",
            "to_language": "yo",
            "glossary": {"Terngi": "Terngi"},
        },
    )

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Ẹ kú àárọ̀ Terngi"
    system = json.loads(route.calls.last.request.content)["messages"][0]["content"]
    assert "Terngi => Terngi" in system


@respx.mock
async def test_morena_uses_placeholders(monkeypatch):
    morena = config.LLMProvider(
        name="morena",
        kind="morena",
        base_url=MORENA_URL,
        api_keys=(),
        models=("morena-1.5b-instruct",),
        requires_key=False,
    )
    monkeypatch.setattr(config, "LLM_PROVIDERS", {"morena": morena})

    route = respx.post(MORENA_URL + "/completion").mock(
        return_value=httpx.Response(200, json={"content": "Ẹ káàbọ̀ \ue0000\ue001"})
    )

    result = await assistant.translate_batch(
        ["Welcome to Terngi"], "en", "yo", "morena", {"Terngi": "Terngi"}
    )

    assert result == ["Ẹ káàbọ̀ Terngi"]
    prompt = json.loads(route.calls.last.request.content)["prompt"]
    assert "Terngi" not in prompt
    assert "\ue0000\ue001" in prompt


@respx.mock
def test_cache_key_includes_the_glossary(client):
    route = respx.post(TRANSLATE_URL).mock(
        side_effect=[azure_ok("Bawo ni"), azure_ok("Bawo ni Terngi")]
    )

    plain = client.post(
        "/v1/translate",
        json={"content": "Hello Terngi", "from_language": "en", "to_language": "yo"},
    )
    glossed = client.post(
        "/v1/translate",
        json={
            "content": "Hello Terngi",
            "from_language": "en",
            "to_language": "yo",
            "glossary": {"Terngi": "Terngi"},
        },
    )
    cached = client.post(
        "/v1/translate",
        json={
            "content": "Hello Terngi",
            "from_language": "en",
            "to_language": "yo",
            "glossary": {"Terngi": "Terngi"},
        },
    )

    assert plain.json()["translated_text"] == "Bawo ni"
    assert glossed.json()["translated_text"] == "Bawo ni Terngi"
    assert cached.json()["translated_text"] == "Bawo ni Terngi"
    assert route.call_count == 2


@respx.mock
def test_batch_translation_applies_the_glossary(client):
    route = respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"translations": [{"text": "Ẹ kú àárọ̀ Terngi"}]},
                {"translations": [{"text": "Ẹ ṣé Terngi"}]},
            ],
        )
    )

    response = client.post(
        "/v1/translate/batch",
        json={
            "texts": ["Good morning Terngi", "Thank you Terngi"],
            "from_language": "en",
            "to_language": "yo",
            "glossary": {"Terngi": "Terngi"},
        },
    )

    assert response.status_code == 200
    texts = [item["text"] for item in json.loads(route.calls.last.request.content)]
    assert all("<mstrans:dictionary" in text for text in texts)


def test_glossary_term_must_not_be_empty(client):
    response = client.post(
        "/v1/translate",
        json={
            "content": "Hello",
            "from_language": "en",
            "to_language": "yo",
            "glossary": {"": "something"},
        },
    )

    assert response.status_code == 422
