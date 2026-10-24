"""
Tests for conversation export and deletion (data access and erasure)
"""

import fakeredis
import httpx
import pytest
import respx

import config
from services import conversations, store
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"
ALICE = {"X-API-Key": "alice"}
BOB = {"X-API-Key": "bob"}
EVESDROPPER = {"X-API-Key": "mallory"}


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    """Give the privacy tests valid API keys so delete-all is allowed"""
    monkeypatch.setattr(config, "API_KEYS", ["alice", "bob"])


def answer(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


def say(client, message, headers):
    return client.post("/v1/chat", json={"message": message, "language": "en"}, headers=headers)


@respx.mock
def test_export_downloads_the_conversation(client):
    respx.post(CHAT_URL).mock(return_value=answer("Hello!"))
    conversation_id = say(client, "Hi", ALICE).json()["conversation_id"]

    response = client.get(f"/v1/chat/{conversation_id}/export", headers=ALICE)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="conversation.json"'
    body = response.json()
    assert body["conversation_id"] == conversation_id
    assert body["exported_at"]
    assert [message["content"] for message in body["messages"]] == ["Hi", "Hello!"]


@respx.mock
def test_export_is_owner_scoped(client):
    respx.post(CHAT_URL).mock(return_value=answer("Hello!"))
    conversation_id = say(client, "Hi", ALICE).json()["conversation_id"]

    assert client.get(f"/v1/chat/{conversation_id}/export", headers=BOB).status_code == 404


@respx.mock
def test_delete_all_only_removes_the_callers_conversations(client):
    respx.post(CHAT_URL).mock(return_value=answer("ok"))
    first = say(client, "One", ALICE).json()["conversation_id"]
    second = say(client, "Two", ALICE).json()["conversation_id"]
    other = say(client, "Mine", BOB).json()["conversation_id"]

    response = client.delete("/v1/chat", headers=ALICE)

    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    assert client.get(f"/v1/chat/{first}", headers=ALICE).status_code == 404
    assert client.get(f"/v1/chat/{second}", headers=ALICE).status_code == 404
    assert client.get(f"/v1/chat/{other}", headers=BOB).status_code == 200
    assert client.get(f"/v1/chat/{other}", headers=ALICE).status_code == 404


def test_delete_all_with_no_conversations(client):
    response = client.delete("/v1/chat", headers=ALICE)

    assert response.status_code == 200
    assert response.json() == {"deleted": 0}


@respx.mock
def test_delete_all_requires_a_valid_api_key(client, monkeypatch):
    respx.post(CHAT_URL).mock(return_value=answer("ok"))
    conversation_id = say(client, "Hi", ALICE).json()["conversation_id"]

    # No key at all: authentication rejects it (401), never IP-based delete-all
    assert client.delete("/v1/chat").status_code == 401
    # A made-up key is rejected too
    assert client.delete("/v1/chat", headers=EVESDROPPER).status_code == 401
    assert client.get(f"/v1/chat/{conversation_id}", headers=ALICE).status_code == 200


@respx.mock
def test_delete_all_is_denied_when_no_api_keys_are_configured(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", [])
    respx.post(CHAT_URL).mock(return_value=answer("ok"))
    say(client, "Hi", ALICE)

    response = client.delete("/v1/chat", headers=ALICE)

    assert response.status_code == 403
    assert "API key" in response.json()["message"]


def test_chat_page_has_delete_all(client):
    response = client.get("/chat")

    assert response.status_code == 200
    assert "Delete my chats" in response.text
    assert 'method: "DELETE"' in response.text
    assert '"/v1/chat"' in response.text


async def test_delete_all_uses_redis_keys(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    store.set_redis(fake)
    redis_store = store.RedisStore("conversation", 3600, max_items=100, enforce_max_items=True)
    monkeypatch.setattr(conversations, "_store", redis_store)

    try:
        alice = await conversations.create("key:alice")
        bob = await conversations.create("key:bob")
        assert set(await redis_store.keys()) == {alice, bob}

        deleted = await conversations.delete_all("key:alice")

        assert deleted == 1
        assert await conversations.get(alice, "key:alice") is None
        assert await conversations.get(bob, "key:bob") == []
        assert set(await redis_store.keys()) == {bob}
    finally:
        store.set_redis(None)
