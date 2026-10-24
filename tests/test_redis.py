"""
Tests for the Redis backend (REDIS_URL): shared translation cache, rate limits and
conversations, using an in-process fake Redis
"""

import asyncio
import json

import fakeredis
import httpx
import pytest
import respx

import config
import middleware
from services import conversations, store, translator

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
PAYLOAD = {"content": "Hello", "from_language": "en", "to_language": "yo"}


@pytest.fixture
def redis(monkeypatch):
    """Switch every shared-state component to Redis, backed by fakeredis"""
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    store.set_redis(fake)
    monkeypatch.setattr(
        translator,
        "translation_cache",
        store.RedisStore("translation", config.CACHE_TTL_SECONDS),
    )
    monkeypatch.setattr(
        conversations,
        "_store",
        store.RedisStore("conversation", config.CONVERSATION_TTL_SECONDS),
    )
    monkeypatch.setattr(middleware, "rate_limiter", store.RedisRateLimiter(limit=60))
    yield fake
    store.set_redis(None)


class BrokenRedis:
    """A Redis client whose every call fails, as if the server were down"""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("redis is down")

        return fail


@pytest.fixture
def redis_down(redis):
    store.set_redis(BrokenRedis())


def azure_ok(text="Bawo ni"):
    return httpx.Response(200, json=[{"translations": [{"text": text}]}])


# --- Translation cache ---------------------------------------------------------------------


@respx.mock
async def test_translation_cache_is_stored_in_redis(client, redis):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_ok())

    first = client.post("/v1/translate", json=PAYLOAD)
    second = client.post("/v1/translate", json=PAYLOAD)

    assert first.json() == second.json()
    assert route.call_count == 1
    keys = await redis.keys("terngi:translation:*")
    assert len(keys) == 1
    assert len(keys[0]) == len("terngi:translation:") + 64  # hashed, fixed length
    assert json.loads(await redis.get(keys[0])) == "Bawo ni"
    assert 0 < await redis.ttl(keys[0]) <= config.CACHE_TTL_SECONDS


@respx.mock
def test_cache_is_shared_between_replicas(client, redis, monkeypatch):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_ok())
    client.post("/v1/translate", json=PAYLOAD)

    # A second replica has its own store object but the same Redis
    monkeypatch.setattr(
        translator, "translation_cache", store.RedisStore("translation", config.CACHE_TTL_SECONDS)
    )
    client.post("/v1/translate", json=PAYLOAD)

    assert route.call_count == 1


@respx.mock
def test_translation_still_works_when_redis_is_down(client, redis_down):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_ok())

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Bawo ni"
    assert route.called


# --- Rate limiter --------------------------------------------------------------------------


def test_rate_limit_is_enforced_through_redis(client, redis, monkeypatch):
    monkeypatch.setattr(middleware.rate_limiter, "limit", 2)
    payload = {"content": "Hi", "from_language": "en", "to_language": "en"}

    responses = [client.post("/v1/translate", json=payload) for _ in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 429]
    assert responses[0].headers["X-RateLimit-Remaining"] == "1"
    assert 1 <= int(responses[2].headers["Retry-After"]) <= 60


async def test_rejected_requests_do_not_use_up_the_window(redis):
    limiter = store.RedisRateLimiter(limit=1)

    assert (await limiter.hit("ip:a"))[0] is True
    assert (await limiter.hit("ip:a"))[0] is False
    assert (await limiter.hit("ip:a"))[0] is False
    assert await redis.zcard("terngi:ratelimit:ip:a") == 1
    assert (await limiter.hit("ip:b"))[0] is True  # clients are independent


def test_rate_limiter_fails_open_when_redis_is_down(client, redis_down, monkeypatch):
    monkeypatch.setattr(middleware.rate_limiter, "limit", 1)
    payload = {"content": "Hi", "from_language": "en", "to_language": "en"}

    statuses = [client.post("/v1/translate", json=payload).status_code for _ in range(3)]

    assert statuses == [200, 200, 200]


# --- Conversations -------------------------------------------------------------------------


GROQ_CHAT = "https://api.groq.com/openai/v1/chat/completions"


def answer(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@respx.mock
async def test_conversations_are_stored_in_redis_and_survive_a_restart(client, redis, monkeypatch):
    respx.post(GROQ_CHAT).mock(side_effect=[answer("Hello Ada!"), answer("Your name is Ada.")])

    first = client.post("/v1/chat", json={"message": "I'm Ada", "language": "en"}).json()
    # Simulate a restart: a brand-new store object, same Redis
    monkeypatch.setattr(
        conversations,
        "_store",
        store.RedisStore("conversation", config.CONVERSATION_TTL_SECONDS),
    )
    second = client.post(
        "/v1/chat",
        json={
            "message": "Who am I?",
            "language": "en",
            "conversation_id": first["conversation_id"],
        },
    ).json()

    assert second["reply"] == "Your name is Ada."
    stored = json.loads(await redis.get(f"terngi:conversation:{first['conversation_id']}"))
    assert [m["content"] for m in stored["messages"]] == [
        "I'm Ada",
        "Hello Ada!",
        "Who am I?",
        "Your name is Ada.",
    ]
    assert "Ada" not in stored["owner"]  # the owner is hashed


@respx.mock
def test_conversations_stay_private_in_redis(client, redis):
    respx.post(GROQ_CHAT).mock(return_value=answer("Hi!"))
    conversation_id = client.post(
        "/v1/chat", json={"message": "Hi", "language": "en"}, headers={"X-API-Key": "alice"}
    ).json()["conversation_id"]

    assert (
        client.get(f"/v1/chat/{conversation_id}", headers={"X-API-Key": "bob"}).status_code == 404
    )
    assert (
        client.delete(f"/v1/chat/{conversation_id}", headers={"X-API-Key": "alice"}).status_code
        == 204
    )
    assert (
        client.get(f"/v1/chat/{conversation_id}", headers={"X-API-Key": "alice"}).status_code == 404
    )


def test_chat_returns_503_when_conversation_storage_is_down(client, redis_down):
    response = client.get("/v1/chat/some-id")

    assert response.status_code == 503
    assert response.json()["message"] == "Conversation storage is unavailable"


# --- Readiness -----------------------------------------------------------------------------


def test_readiness_reports_redis(client, redis, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.get("/health/ready", headers={"X-API-Key": "secret"})

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["services"]["storage"] is True


def test_readiness_degrades_when_redis_is_down(client, redis_down, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.get("/health/ready", headers={"X-API-Key": "secret"})

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["services"]["storage"] is False
    assert response.json()["services"]["translator"] is True


@pytest.mark.asyncio
async def test_redis_store_enforces_the_conversation_key_cap(redis):
    capped = store.RedisStore(
        "conversation",
        config.CONVERSATION_TTL_SECONDS,
        max_items=2,
        enforce_max_items=True,
    )

    await capped.set("a", {"owner": "x", "messages": []})
    await capped.set("b", {"owner": "x", "messages": []})
    await capped.set("c", {"owner": "x", "messages": []})

    fake = store.get_redis()
    index_key = "terngi:conversation:__index"
    assert await fake.zcard(index_key) == 2
    assert await fake.exists("terngi:conversation:a") == 0
    assert await fake.exists("terngi:conversation:b") == 1
    assert await fake.exists("terngi:conversation:c") == 1

    await capped.delete("c")
    assert await fake.zcard(index_key) == 1
    assert await fake.exists("terngi:conversation:c") == 0


@pytest.mark.asyncio
async def test_redis_store_cap_keeps_recently_updated_conversations(redis):
    capped = store.RedisStore(
        "conversation",
        config.CONVERSATION_TTL_SECONDS,
        max_items=2,
        enforce_max_items=True,
    )

    await capped.set("a", {"owner": "x", "messages": []})
    await capped.set("b", {"owner": "x", "messages": []})
    await asyncio.sleep(0.01)
    await capped.update("a", lambda entry: entry)
    await capped.set("c", {"owner": "x", "messages": []})

    fake = store.get_redis()
    assert await fake.exists("terngi:conversation:a") == 1
    assert await fake.exists("terngi:conversation:b") == 0
    assert await fake.exists("terngi:conversation:c") == 1


def test_in_memory_storage_without_redis_url(monkeypatch):
    monkeypatch.setattr(config, "REDIS_URL", "")

    assert isinstance(store.make_store("x", 10, 60), store.MemoryStore)
    assert not store.using_redis()
