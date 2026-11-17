"""
Tests for rate limiting of failed API-key authentications (issue #82)
"""

import fakeredis
import httpx
import respx

import config
import middleware
from main import app
from services import store

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"

PAYLOAD = {"content": "Hi", "from_language": "en", "to_language": "yo"}


def _transport(ip: str):
    return httpx.ASGITransport(app=app, client=(ip, 12345))


async def _post(transport, headers=None):
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.post("/v1/translate", json=PAYLOAD, headers=headers)


@respx.mock
async def test_failed_attempts_are_throttled_per_ip(monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])
    monkeypatch.setattr(middleware, "auth_failure_limiter", middleware.RateLimiter(limit=2))
    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(200, json=[{"translations": [{"text": "Bawo ni"}]}])
    )

    attacker = _transport("203.0.113.5")
    assert (await _post(attacker, {"X-API-Key": "wrong"})).status_code == 401
    assert (await _post(attacker, {"X-API-Key": "wrong"})).status_code == 401

    throttled = await _post(attacker, {"X-API-Key": "wrong"})
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers
    assert "Too many failed authentication attempts" in throttled.json()["message"]

    # Missing keys count the same way
    assert (await _post(attacker)).status_code == 429

    # A different IP has its own budget
    other = _transport("198.51.100.9")
    assert (await _post(other, {"X-API-Key": "wrong"})).status_code == 401

    # The valid key still works, from the throttled IP too
    ok = await _post(attacker, {"X-API-Key": "secret"})
    assert ok.status_code == 200


@respx.mock
async def test_valid_keys_are_not_counted_as_failures(monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])
    limiter = middleware.RateLimiter(limit=2)
    monkeypatch.setattr(middleware, "auth_failure_limiter", limiter)
    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(200, json=[{"translations": [{"text": "Bawo ni"}]}])
    )

    transport = _transport("203.0.113.5")
    assert (await _post(transport, {"X-API-Key": "secret"})).status_code == 200
    assert (await _post(transport, {"X-API-Key": "secret"})).status_code == 200

    # Still only one failure used; the second wrong key still 401s, not 429
    assert (await _post(transport, {"X-API-Key": "wrong"})).status_code == 401


async def test_auth_failures_are_shared_through_redis(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    store.set_redis(fake)
    monkeypatch.setattr(config, "API_KEYS", ["secret"])
    monkeypatch.setattr(middleware, "auth_failure_limiter", store.RedisRateLimiter(limit=2))
    try:
        attacker = _transport("203.0.113.5")
        assert (await _post(attacker, {"X-API-Key": "wrong"})).status_code == 401
        assert (await _post(attacker, {"X-API-Key": "wrong"})).status_code == 401

        # A second replica shares the same Redis counters
        monkeypatch.setattr(middleware, "auth_failure_limiter", store.RedisRateLimiter(limit=2))
        throttled = await _post(attacker, {"X-API-Key": "wrong"})
        assert throttled.status_code == 429
    finally:
        store.set_redis(None)
