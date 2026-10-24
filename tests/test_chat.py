"""
Tests for conversational chat with server-side memory, and the web chat page
"""

import json

import httpx
import respx

import config
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"


def answer(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


def say(client, message, conversation_id=None, headers=None, **extra):
    body = {"message": message, "language": "en", **extra}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return client.post("/v1/chat", json=body, headers=headers or {})


@respx.mock
def test_chat_remembers_the_conversation(client):
    route = respx.post(CHAT_URL).mock(
        side_effect=[answer("Nice to meet you, Ada!"), answer("Your name is Ada.")]
    )

    first = say(client, "Hi, my name is Ada").json()
    second = say(client, "What is my name?", first["conversation_id"]).json()

    assert first["reply"] == "Nice to meet you, Ada!"
    assert second["conversation_id"] == first["conversation_id"]
    assert second["reply"] == "Your name is Ada."
    messages = json.loads(route.calls[1].request.content)["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "Hi, my name is Ada"
    assert messages[2]["content"] == "Nice to meet you, Ada!"


@respx.mock
def test_chat_is_a_general_assistant(client):
    route = respx.post(CHAT_URL).mock(return_value=answer("Compound interest is..."))

    say(client, "Explain compound interest")

    system = json.loads(route.calls.last.request.content)["messages"][0]["content"]
    assert "Chat naturally about anything" in system
    assert "Remember what the user said earlier" in system


@respx.mock
def test_get_and_delete_conversation(client):
    respx.post(CHAT_URL).mock(return_value=answer("Hello!"))
    conversation_id = say(client, "Hi").json()["conversation_id"]

    history = client.get(f"/v1/chat/{conversation_id}").json()
    assert history["messages"] == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
    ]

    assert client.delete(f"/v1/chat/{conversation_id}").status_code == 204
    assert client.get(f"/v1/chat/{conversation_id}").status_code == 404


def test_unknown_conversation_returns_404(client):
    assert say(client, "Hi", "does-not-exist").status_code == 404


@respx.mock
def test_conversations_are_private_to_their_owner(client):
    respx.post(CHAT_URL).mock(return_value=answer("Hello!"))
    conversation_id = say(client, "Hi", headers={"X-API-Key": "alice"}).json()["conversation_id"]

    other = {"X-API-Key": "bob"}
    assert client.get(f"/v1/chat/{conversation_id}", headers=other).status_code == 404
    assert say(client, "Hi", conversation_id, headers=other).status_code == 404
    assert client.delete(f"/v1/chat/{conversation_id}", headers=other).status_code == 404
    assert (
        client.get(f"/v1/chat/{conversation_id}", headers={"X-API-Key": "alice"}).status_code == 200
    )


@respx.mock
def test_history_is_capped(client, monkeypatch):
    monkeypatch.setattr(config, "CONVERSATION_MAX_MESSAGES", 4)
    respx.post(CHAT_URL).mock(return_value=answer("ok"))

    conversation_id = say(client, "one").json()["conversation_id"]
    for text in ["two", "three"]:
        say(client, text, conversation_id)

    messages = client.get(f"/v1/chat/{conversation_id}").json()["messages"]
    assert [m["content"] for m in messages] == ["two", "ok", "three", "ok"]


@respx.mock
def test_provider_history_is_bounded_by_characters(client, monkeypatch):
    monkeypatch.setattr(config, "CONVERSATION_MAX_CHARS", 12)
    route = respx.post(CHAT_URL).mock(return_value=answer("ok"))

    conversation_id = say(client, "one").json()["conversation_id"]
    for text in ["two", "three", "four"]:
        say(client, text, conversation_id)

    sent = json.loads(route.calls[-1].request.content)["messages"]
    history = sent[1:-1]
    assert [message["content"] for message in history] == ["two", "ok", "three", "ok"]
    assert sum(len(message["content"]) for message in history) <= 12


def test_failed_reply_is_not_stored(client, monkeypatch):
    monkeypatch.setattr(config, "AGENT_PROVIDERS", [])

    assert say(client, "Hi").status_code == 503


def test_chat_page_is_served(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.get("/chat")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Terngi" in response.text
    assert "/v1/chat" in response.text


# --- Languages per provider --------------------------------------------------


@respx.mock
def test_morena_is_only_used_for_its_languages(client, monkeypatch):
    morena = config.LLMProvider(
        name="morena",
        kind="morena",
        base_url="http://localhost:8080",
        api_keys=(),
        models=("morena-1.5b-instruct",),
        requires_key=False,
        languages=config.MORENA_LANGUAGES,
    )
    monkeypatch.setattr(config, "LLM_PROVIDERS", {**config.LLM_PROVIDERS, "morena": morena})
    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["morena", "groq"])
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    morena_route = respx.post("http://localhost:8080/completion").mock(
        return_value=httpx.Response(200, json={"content": "Habari"})
    )
    groq_route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "你好"}}]})
    )

    swahili = client.post(
        "/v1/translate", json={"content": "Hello", "from_language": "en", "to_language": "sw"}
    )
    chinese = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "zh-Hans"},
    )

    assert swahili.json()["translated_text"] == "Habari"
    assert chinese.json()["translated_text"] == "你好"
    assert morena_route.call_count == 1
    assert groq_route.call_count == 1
