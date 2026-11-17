"""
Tests for the WhatsApp bot: webhook verification and signatures, answers in the sender's
language, commands, retries of the same message, and sending
"""

import hashlib
import hmac
import json

import httpx
import pytest
import respx

import config
from services import whatsapp
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"
TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
DETECT_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/detect"
GRAPH = "https://graph.test/v23.0"
SEND_URL = GRAPH + "/1234567890/messages"
APP_SECRET = "test-app-secret"


@pytest.fixture(autouse=True)
def whatsapp_config(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "EAAG-test-token")
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setattr(config, "WHATSAPP_GRAPH_URL", GRAPH)
    monkeypatch.setattr(config, "WHATSAPP_CONTEXT", "")
    monkeypatch.setattr(config, "WHATSAPP_WELCOME", "")


def answer(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


def detected(language: str) -> httpx.Response:
    return httpx.Response(200, json=[{"language": language, "score": 0.99}])


def graph() -> list:
    """Mock Meta's API and record what is sent"""
    sent: list = []

    def reply(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer EAAG-test-token"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.out{len(sent)}"}]})

    respx.post(SEND_URL).mock(side_effect=reply)
    return sent


def deliver(client, text=None, message_id="wamid.in1", phone="2348012345678", kind="text"):
    message = {"from": phone, "id": message_id, "type": kind}
    if text is not None:
        message["text"] = {"body": text}
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}).encode()
    signature = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/v1/whatsapp/webhook",
        content=body,
        headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
    )


# --- Webhook ---------------------------------------------------------------------------


def test_webhook_verification(client):
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "test-verify-token",
        "hub.challenge": "42",
    }
    assert client.get("/v1/whatsapp/webhook", params=params).text == "42"
    wrong = {**params, "hub.verify_token": "wrong"}
    assert client.get("/v1/whatsapp/webhook", params=wrong).status_code == 403


def test_webhook_needs_a_valid_signature(client):
    response = client.post(
        "/v1/whatsapp/webhook", content=b"{}", headers={"X-Hub-Signature-256": "sha256=bad"}
    )
    assert response.status_code == 401


def test_webhook_works_without_an_api_key(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["client-key"])
    assert deliver(client, None, kind="image").status_code == 200


def test_off_until_configured(client, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "")
    assert client.get("/v1/whatsapp/webhook").status_code == 503
    assert (
        client.post("/v1/whatsapp/send", json={"to": "+447700900123", "text": "Hi"}).status_code
        == 503
    )


# --- The bot ---------------------------------------------------------------------------


@respx.mock
def test_bot_answers_and_remembers(client, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_CONTEXT", "Open 9am to 6pm, Monday to Saturday.")
    monkeypatch.setattr(config, "WHATSAPP_WELCOME", "Welcome to Ade's Kitchen!")
    sent = graph()
    respx.post(DETECT_URL).mock(return_value=detected("en"))
    llm = respx.post(CHAT_URL).mock(
        side_effect=[answer("We open at 9am."), answer("Yes, until 6pm.")]
    )

    assert deliver(client, "When do you open?").json() == {"status": "ok"}
    assert sent[0]["to"] == "2348012345678"
    assert sent[0]["text"]["body"] == "Welcome to Ade's Kitchen!\n\nWe open at 9am."
    system = json.loads(llm.calls[0].request.content)["messages"][0]["content"]
    assert "Open 9am to 6pm, Monday to Saturday." in system

    deliver(client, "Are you open on Saturday?", message_id="wamid.in2")
    assert sent[1]["text"]["body"] == "Yes, until 6pm."  # no second welcome
    history = json.loads(llm.calls[1].request.content)["messages"]
    assert [m["content"] for m in history[1:3]] == ["When do you open?", "We open at 9am."]


@respx.mock
def test_retried_messages_are_answered_once(client):
    sent = graph()
    respx.post(DETECT_URL).mock(return_value=detected("en"))
    respx.post(CHAT_URL).mock(return_value=answer("Hello!"))
    deliver(client, "Hi")
    deliver(client, "Hi")
    assert len(sent) == 1


@respx.mock
def test_language_command_keeps_command_words(client):
    sent = graph()
    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200, json=[{"translations": [{"text": "Harshenka yanzu Hausa ne."}]}]
        )
    )
    deliver(client, "LANGUAGE hausa")
    assert sent[0]["text"]["body"] == "Harshenka yanzu Hausa ne."

    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(
            200, json=[{"translations": [{"text": "Aika [[A]] don canza harshe"}]}]
        )
    )
    deliver(client, "HELP", message_id="wamid.in2")
    assert sent[1]["text"]["body"].startswith("Aika LANGUAGE don canza harshe")


@respx.mock
def test_help_reset_and_unsupported_messages(client):
    sent = graph()
    deliver(client, "help")
    assert "LANGUAGE" in sent[0]["text"]["body"] and "RESET" in sent[0]["text"]["body"]
    deliver(client, "RESET", message_id="wamid.in2")
    assert "new conversation" in sent[1]["text"]["body"]
    deliver(client, None, message_id="wamid.in3", kind="audio")
    assert "text messages" in sent[2]["text"]["body"]
    deliver(client, "LANGUAGE Klingon", message_id="wamid.in4")
    assert "Which language" in sent[3]["text"]["body"]


@respx.mock
def test_bot_apologises_when_the_agent_fails(client):
    sent = graph()
    respx.post(DETECT_URL).mock(return_value=detected("en"))
    respx.post(CHAT_URL).mock(return_value=httpx.Response(500, json={}))
    deliver(client, "Hello")
    assert "couldn't answer" in sent[0]["text"]["body"]


# --- Sending ---------------------------------------------------------------------------


@respx.mock
def test_send_translated_text(client):
    sent = graph()
    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(200, json=[{"translations": [{"text": "Ẹ kú àárọ̀"}]}])
    )
    response = client.post(
        "/v1/whatsapp/send",
        json={"to": "+44 7700 900123", "text": "Good morning", "to_language": "yo"},
    )
    assert response.json() == {
        "to": "447700900123",
        "message_ids": ["wamid.out1"],
        "text": "Ẹ kú àárọ̀",
    }
    assert sent[0]["text"]["body"] == "Ẹ kú àárọ̀"


@respx.mock
def test_send_template(client):
    sent = graph()
    client.post(
        "/v1/whatsapp/send",
        json={
            "to": "447700900123",
            "template": {"name": "order_ready", "language": "en_GB", "parameters": ["A-102"]},
        },
    )
    assert sent[0]["template"] == {
        "name": "order_ready",
        "language": {"code": "en_GB"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": "A-102"}]}],
    }


@respx.mock
def test_send_errors(client):
    assert client.post("/v1/whatsapp/send", json={"to": "447700900123"}).status_code == 400
    assert client.post("/v1/whatsapp/send", json={"to": "12", "text": "Hi"}).status_code == 400
    respx.post(SEND_URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "Recipient not in allowed list"}}
        )
    )
    response = client.post("/v1/whatsapp/send", json={"to": "447700900123", "text": "Hi"})
    assert response.status_code == 502
    assert "Recipient not in allowed list" in response.json()["message"]


def test_send_needs_the_api_key(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["client-key"])
    assert (
        client.post("/v1/whatsapp/send", json={"to": "447700900123", "text": "Hi"}).status_code
        == 401
    )


# --- Helpers ---------------------------------------------------------------------------


def test_split_and_languages():
    parts = whatsapp.split(("word " * 2000).strip())
    assert len(parts) == 3 and all(len(p) <= whatsapp.MAX_TEXT for p in parts)
    assert whatsapp.find_language("Yoruba") == "yo"
    assert whatsapp.find_language("pidgin") == "pcm"
    assert whatsapp.find_language("Klingon") is None
    assert whatsapp.normalise_phone("+44 (0)7700-900123") == "4407700900123"
