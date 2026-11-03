"""
Tests for detection, batch translation, caching, auth, rate limiting and readiness
"""

import logging

import httpx
import respx

import config
import middleware
from services.cache import TTLCache

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
DETECT_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/detect"


def azure_translations(*texts: str) -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": t}]} for t in texts])


def azure_detected(language: str, score: float = 0.98) -> httpx.Response:
    return httpx.Response(200, json=[{"language": language, "score": score}])


# --- Language detection -----------------------------------------------------


@respx.mock
def test_detect_supported_language(client):
    respx.post(DETECT_URL).mock(return_value=azure_detected("yo"))

    response = client.post("/v1/detect", json={"content": "Bawo ni"})

    assert response.status_code == 200
    assert response.json() == {
        "language": "yo",
        "language_name": "Yoruba",
        "score": 0.98,
        "is_supported": True,
    }


@respx.mock
def test_detect_unsupported_language(client):
    respx.post(DETECT_URL).mock(return_value=azure_detected("tlh-Latn"))

    response = client.post("/v1/detect", json={"content": "Guten Morgen"})

    assert response.status_code == 200
    assert response.json()["is_supported"] is False
    assert response.json()["language_name"] is None


@respx.mock
def test_translate_auto_detects_source(client):
    respx.post(DETECT_URL).mock(return_value=azure_detected("ha"))
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_translations("Good morning"))

    response = client.post(
        "/v1/translate",
        json={"content": "Ina kwana", "from_language": "auto", "to_language": "en"},
    )

    assert response.status_code == 200
    assert response.json()["from_language"] == "ha"
    assert route.calls.last.request.url.params["from"] == "ha"


@respx.mock
def test_translate_auto_rejects_unsupported_detection(client):
    respx.post(DETECT_URL).mock(return_value=azure_detected("tlh-Latn"))

    response = client.post(
        "/v1/translate",
        json={"content": "Guten Morgen", "from_language": "auto", "to_language": "en"},
    )

    assert response.status_code == 400


# --- Batch translation ------------------------------------------------------


@respx.mock
def test_batch_translation(client):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_translations("Bawo ni", "O dabo"))

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["Hello", "Goodbye"], "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 200
    assert response.json()["translations"] == ["Bawo ni", "O dabo"]
    assert route.call_count == 1


@respx.mock
def test_batch_only_sends_uncached_texts(client):
    respx.post(TRANSLATE_URL).mock(
        side_effect=[azure_translations("Bawo ni"), azure_translations("O dabo")]
    )
    client.post(
        "/v1/translate", json={"content": "Hello", "from_language": "en", "to_language": "yo"}
    )

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["Hello", "Goodbye"], "from_language": "en", "to_language": "yo"},
    )

    assert response.json()["translations"] == ["Bawo ni", "O dabo"]
    assert respx.calls.last.request.content == b'[{"text":"Goodbye"}]'


def test_batch_rejects_too_many_texts(client):
    response = client.post(
        "/v1/translate/batch",
        json={
            "texts": ["a"] * (config.MAX_BATCH_SIZE + 1),
            "from_language": "en",
            "to_language": "yo",
        },
    )

    assert response.status_code == 422


def test_batch_rejects_too_many_characters(client, monkeypatch):
    monkeypatch.setattr("routes.translation.MAX_BATCH_CHARACTERS", 5)

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["abc", "def"], "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 400


@respx.mock
def test_batch_mismatched_upstream_count(client):
    respx.post(TRANSLATE_URL).mock(return_value=azure_translations("only one"))

    response = client.post(
        "/v1/translate/batch",
        json={"texts": ["a", "b"], "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 502


# --- Caching ----------------------------------------------------------------


@respx.mock
def test_repeat_translation_is_cached(client):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_translations("Bawo ni"))
    payload = {"content": "Hello", "from_language": "en", "to_language": "yo"}

    first = client.post("/v1/translate", json=payload)
    second = client.post("/v1/translate", json=payload)

    assert first.json() == second.json()
    assert route.call_count == 1


@respx.mock
def test_key_scope_isolates_the_cache_between_api_keys(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["key-a", "key-b"])
    monkeypatch.setattr(config, "CACHE_SCOPE", "key")
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_translations("Bawo ni"))
    payload = {"content": "Hello", "from_language": "en", "to_language": "yo"}

    first = client.post("/v1/translate", json=payload, headers={"X-API-Key": "key-a"})
    second = client.post("/v1/translate", json=payload, headers={"X-API-Key": "key-b"})
    third = client.post("/v1/translate", json=payload, headers={"X-API-Key": "key-a"})

    for response in (first, second, third):
        assert response.json()["translated_text"] == "Bawo ni"
    # key-b couldn't reuse key-a's cached translation, but key-a reuses its own
    assert route.call_count == 2


@respx.mock
def test_global_scope_shares_the_cache_between_api_keys(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["key-a", "key-b"])
    monkeypatch.setattr(config, "CACHE_SCOPE", "global")
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_translations("Bawo ni"))
    payload = {"content": "Hello", "from_language": "en", "to_language": "yo"}

    client.post("/v1/translate", json=payload, headers={"X-API-Key": "key-a"})
    client.post("/v1/translate", json=payload, headers={"X-API-Key": "key-b"})

    assert route.call_count == 1


def test_cache_expires_and_evicts(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("services.cache.time.monotonic", lambda: now[0])
    cache = TTLCache(max_items=2, ttl=10)

    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")  # "a" becomes most recently used
    cache.set("c", 3)  # evicts "b"
    assert cache.get("b") is None
    assert cache.get("a") == 1

    now[0] += 11
    assert cache.get("a") is None


def test_cache_disabled_when_ttl_zero():
    cache = TTLCache(max_items=10, ttl=0)
    cache.set("a", 1)
    assert cache.get("a") is None
    assert len(cache) == 0


# --- Authentication ---------------------------------------------------------


def test_auth_required_when_keys_configured(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret-1"])
    payload = {"content": "Hi", "from_language": "en", "to_language": "en"}

    missing = client.post("/v1/translate", json=payload)
    wrong = client.post("/v1/translate", json=payload, headers={"X-API-Key": "nope"})
    ok = client.post("/v1/translate", json=payload, headers={"X-API-Key": "secret-1"})

    assert missing.status_code == 401
    assert missing.json()["error"] is True
    assert wrong.status_code == 401
    assert ok.status_code == 200


def test_public_paths_skip_auth(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret-1"])

    assert client.get("/health").status_code == 200
    assert client.get("/v1/languages").status_code == 200


# --- Rate limiting ----------------------------------------------------------


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(middleware.rate_limiter, "limit", 2)
    payload = {"content": "Hi", "from_language": "en", "to_language": "en"}

    first = client.post("/v1/translate", json=payload)
    second = client.post("/v1/translate", json=payload)
    third = client.post("/v1/translate", json=payload)

    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.status_code == 200
    assert third.status_code == 429
    assert int(third.headers["Retry-After"]) >= 1


def test_rate_limit_is_per_valid_api_key(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["a", "b"])
    monkeypatch.setattr(middleware.rate_limiter, "limit", 1)
    payload = {"content": "Hi", "from_language": "en", "to_language": "en"}

    a = client.post("/v1/translate", json=payload, headers={"X-API-Key": "a"})
    b = client.post("/v1/translate", json=payload, headers={"X-API-Key": "b"})

    assert a.status_code == 200
    assert b.status_code == 200


def test_made_up_api_keys_cannot_bypass_rate_limit(client, monkeypatch):
    # With auth disabled, X-API-Key is unverified: every made-up key shares the IP's limit
    monkeypatch.setattr(middleware.rate_limiter, "limit", 2)
    payload = {"content": "Hi", "from_language": "en", "to_language": "en"}

    statuses = [
        client.post("/v1/translate", json=payload, headers={"X-API-Key": f"fake-{i}"}).status_code
        for i in range(4)
    ]

    assert statuses == [200, 200, 429, 429]


async def test_rate_limiter_forgets_idle_clients(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(middleware.time, "monotonic", lambda: now[0])
    limiter = middleware.RateLimiter(limit=5, window=60)

    for i in range(999):
        await limiter.hit(f"ip:{i}")
    now[0] = 120  # every client has been idle for longer than the window
    await limiter.hit("ip:fresh")  # the 1000th call triggers a sweep

    assert set(limiter._hits) == {"ip:fresh"}


# --- Request context & readiness --------------------------------------------


def test_request_id_is_generated_and_echoed(client):
    generated = client.get("/health")
    echoed = client.get("/health", headers={"X-Request-ID": "abc123"})

    assert len(generated.headers["X-Request-ID"]) == 32
    assert echoed.headers["X-Request-ID"] == "abc123"
    assert "X-Process-Time-Ms" in echoed.headers


def test_malformed_or_oversized_request_ids_are_replaced(client):
    # A 129-char ID and IDs with spaces / newlines are rejected (a real client can
    # also send non-ASCII or empty values; the regex rejects those too)
    for bad in ["a" * 129, "has space", "log\ninjection: x", ""]:
        response = client.get("/health", headers={"X-Request-ID": bad})
        echoed = response.headers["X-Request-ID"]
        assert echoed != bad
        assert middleware.REQUEST_ID_RE.match(echoed)

    # A valid ID at the size limit (128) is still accepted
    boundary = "a" * 128
    assert (
        client.get("/health", headers={"X-Request-ID": boundary}).headers["X-Request-ID"]
        == boundary
    )


def test_access_log_uses_route_template_not_raw_path(client, caplog):
    conversation_id = "conversation-secret-abc123"

    with caplog.at_level(logging.INFO, logger="middleware"):
        client.get(f"/v1/chat/{conversation_id}")

    logged = "\n".join(r.getMessage() for r in caplog.records if r.name == "middleware")
    assert conversation_id not in logged
    assert "/v1/chat/{conversation_id}" in logged


def test_ready_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.get("/health/ready", headers={"X-API-Key": "secret"})

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["services"] == {
        "translator": True,
        "llm": True,
        "agent": True,
        "storage": True,
        "auth": True,
    }


def test_ready_not_degraded_when_auth_is_off(client):
    # No API keys configured: auth is reported off, but readiness stays "ready"
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert "services" not in response.json()


def test_ready_hides_service_details_from_strangers(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert "services" not in response.json()


def test_ready_is_degraded_when_agent_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(config, "AGENT_PROVIDERS", [])
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.get("/health/ready", headers={"X-API-Key": "secret"})

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["services"]["agent"] is False
    assert response.json()["services"]["translator"] is True


def test_not_ready_without_keys(client, monkeypatch):
    monkeypatch.setattr(config, "CHAT_PROVIDERS", [])
    monkeypatch.setattr(config, "AGENT_PROVIDERS", [])
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.get("/health/ready", headers={"X-API-Key": "secret"})

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["services"]["translator"] is False
    assert response.json()["services"]["llm"] is False
