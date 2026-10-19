"""
Tests for the Prometheus /metrics endpoint
"""

from typing import Optional

import httpx
import pytest
import respx
from prometheus_client import REGISTRY

import config
from middleware import rate_limiter
from services import groq_service

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
PAYLOAD = {"content": "Hello", "from_language": "en", "to_language": "yo"}


def sample(name: str, **labels: str) -> float:
    value: Optional[float] = REGISTRY.get_sample_value(name, labels)
    return value or 0.0


def azure_ok(text: str = "Bawo ni") -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": text, "to": "yo"}]}])


def test_metrics_endpoint_serves_prometheus_text(client):
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "terngi_http_requests_total" in response.text
    assert 'route="/health"' in response.text


def test_metrics_is_public_and_not_rate_limited(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])
    monkeypatch.setattr(rate_limiter, "limit", 1)

    for _ in range(3):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers


def test_requests_counted_by_route_template_and_status(client):
    before_ok = sample("terngi_http_requests_total", method="GET", route="/health", status="200")
    before_404 = sample("terngi_http_requests_total", method="GET", route="unmatched", status="404")

    client.get("/health")
    client.get("/no/such/path")

    assert (
        sample("terngi_http_requests_total", method="GET", route="/health", status="200")
        == before_ok + 1
    )
    assert (
        sample("terngi_http_requests_total", method="GET", route="unmatched", status="404")
        == before_404 + 1
    )
    assert sample("terngi_http_request_duration_seconds_count", method="GET", route="/health") > 0


def test_unknown_methods_are_bucketed(client):
    before = sample("terngi_http_requests_total", method="OTHER", route="/health", status="405")

    client.request("BREW", "/health")

    assert (
        sample("terngi_http_requests_total", method="OTHER", route="/health", status="405")
        == before + 1
    )


def test_rejections_keep_route_label(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])
    before = sample(
        "terngi_http_requests_total", method="POST", route="/v1/translate", status="401"
    )

    response = client.post("/v1/translate", json=PAYLOAD)

    assert response.status_code == 401
    assert (
        sample("terngi_http_requests_total", method="POST", route="/v1/translate", status="401")
        == before + 1
    )


@respx.mock
def test_rate_limited_requests_counted(client, monkeypatch):
    monkeypatch.setattr(rate_limiter, "limit", 1)
    respx.post(TRANSLATE_URL).mock(return_value=azure_ok())
    before = sample("terngi_rate_limited_requests_total")

    assert client.post("/v1/translate", json=PAYLOAD).status_code == 200
    assert client.post("/v1/translate", json=PAYLOAD).status_code == 429

    assert sample("terngi_rate_limited_requests_total") == before + 1


@respx.mock
def test_azure_calls_and_cache_counted(client):
    respx.post(TRANSLATE_URL).mock(return_value=azure_ok())
    before_ok = sample("terngi_upstream_requests_total", service="azure", outcome="success")
    before_hit = sample("terngi_translation_cache_lookups_total", result="hit")
    before_miss = sample("terngi_translation_cache_lookups_total", result="miss")

    client.post("/v1/translate", json=PAYLOAD)  # miss -> Azure call
    client.post("/v1/translate", json=PAYLOAD)  # hit -> no call

    assert (
        sample("terngi_upstream_requests_total", service="azure", outcome="success")
        == before_ok + 1
    )
    assert sample("terngi_translation_cache_lookups_total", result="miss") == before_miss + 1
    assert sample("terngi_translation_cache_lookups_total", result="hit") == before_hit + 1
    assert sample("terngi_upstream_request_duration_seconds_count", service="azure") > 0


@respx.mock
def test_azure_errors_counted(client):
    respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(500))
    before = sample("terngi_upstream_requests_total", service="azure", outcome="error")

    assert client.post("/v1/translate", json=PAYLOAD).status_code == 502

    assert sample("terngi_upstream_requests_total", service="azure", outcome="error") == before + 1


@pytest.mark.parametrize(("error", "outcome"), [(None, "success"), (RuntimeError("boom"), "error")])
async def test_groq_calls_counted(monkeypatch, error, outcome):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    create = AsyncMock(
        side_effect=error,
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Hi"))]
        ),
    )
    client = MagicMock()
    client.chat.completions.create = create
    monkeypatch.setattr(groq_service, "get_client", lambda: client)
    before = sample("terngi_upstream_requests_total", service="groq", outcome=outcome)

    try:
        await groq_service.get_response("Hello")
    except groq_service.HTTPException:
        pass

    assert sample("terngi_upstream_requests_total", service="groq", outcome=outcome) == before + 1
