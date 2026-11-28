"""
Tests for refusing a plain-text remote Redis (#167)
"""

import logging
from pathlib import Path

import pytest

import config
import main
from services import redis_security

SECRET = "s3cret-redis-password"


@pytest.mark.parametrize(
    "url, where, tls, auth",
    [
        ("redis://localhost:6379/0", "local", False, False),
        ("redis://127.0.0.1:6379", "local", False, False),
        ("redis://[::1]:6379", "local", False, False),
        ("unix:///var/run/redis.sock", "local", False, False),
        ("redis://redis:6379/0", "private", False, False),  # the bundled compose stack
        ("redis://cache.internal:6379", "private", False, False),
        ("redis://10.0.3.7:6379", "private", False, False),
        ("redis://192.168.1.20:6379", "private", False, False),
        ("redis://red-abc123:6379", "private", False, False),  # managed, private network
        ("redis://:pw@redis.example.com:6379", "remote", False, True),
        ("rediss://default:pw@redis.example.com:6380", "remote", True, True),
        ("redis://93.184.216.34:6379", "remote", False, False),
    ],
)
def test_urls_are_classified(url, where, tls, auth):
    assert redis_security.describe(url) == redis_security.RedisConnection(where, tls, auth)


def test_only_plain_text_remote_connections_are_refused():
    refused = redis_security.refused
    assert refused(redis_security.describe("redis://:pw@redis.example.com:6379"))
    assert not refused(redis_security.describe("rediss://:pw@redis.example.com:6380"))
    assert not refused(redis_security.describe("redis://redis:6379/0"))
    assert not refused(redis_security.describe("redis://localhost:6379"))


def test_startup_refuses_a_plain_text_remote_redis(monkeypatch):
    monkeypatch.setattr(config, "REDIS_URL", f"redis://:{SECRET}@redis.example.com:6379")
    monkeypatch.setattr(config, "ALLOW_INSECURE_REDIS", False)

    with pytest.raises(SystemExit) as exc:
        main.check_redis()

    assert "without TLS" in str(exc.value)
    assert SECRET not in str(exc.value)


def test_the_flag_allows_it_with_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(config, "REDIS_URL", f"redis://:{SECRET}@redis.example.com:6379")
    monkeypatch.setattr(config, "ALLOW_INSECURE_REDIS", True)

    with caplog.at_level(logging.WARNING, logger="main"):
        main.check_redis()

    assert any("ALLOW_INSECURE_REDIS=true" in r.message for r in caplog.records)
    assert not any(SECRET in r.getMessage() for r in caplog.records)


def test_tls_with_a_password_starts_quietly(monkeypatch, caplog):
    monkeypatch.setattr(config, "REDIS_URL", f"rediss://default:{SECRET}@redis.example.com:6380")

    with caplog.at_level(logging.WARNING, logger="main"):
        main.check_redis()

    assert not caplog.records


def test_the_compose_stack_starts_with_warnings(monkeypatch, caplog):
    monkeypatch.setattr(config, "REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(config, "ALLOW_INSECURE_REDIS", False)

    with caplog.at_level(logging.WARNING, logger="main"):
        main.check_redis()  # must not raise

    messages = " ".join(r.message for r in caplog.records)
    assert "without TLS" in messages and "no password" in messages


def test_the_bundled_compose_url_is_never_refused():
    compose = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text()
    url = next(
        line.split(":", 1)[1].strip() for line in compose.splitlines() if "REDIS_URL" in line
    )
    assert not redis_security.refused(redis_security.describe(url))


def test_local_redis_and_no_redis_need_nothing(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="main"):
        monkeypatch.setattr(config, "REDIS_URL", "")
        main.check_redis()
        monkeypatch.setattr(config, "REDIS_URL", "redis://localhost:6379/0")
        main.check_redis()

    assert not caplog.records


def test_readiness_reports_tls_and_auth_but_never_the_url(client, monkeypatch):
    monkeypatch.setattr(config, "REDIS_URL", f"rediss://default:{SECRET}@redis.example.com:6380")

    async def ping():
        return True

    monkeypatch.setattr("services.store.ping", ping)

    response = client.get("/health/ready")

    assert response.json()["redis"] == {"network": "remote", "tls": True, "auth": True}
    assert SECRET not in response.text and "redis.example.com" not in response.text
