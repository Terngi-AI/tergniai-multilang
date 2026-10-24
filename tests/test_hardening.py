"""
Tests for security headers, request body limits and trusted proxy headers
"""

import httpx
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import config
import middleware
from services import conversations


def test_security_headers_on_api_responses(client):
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Content-Security-Policy"] == middleware.API_CSP
    assert "Strict-Transport-Security" not in response.headers  # plain HTTP


def test_security_headers_on_rejected_requests(client, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["secret"])

    response = client.post(
        "/v1/translate", json={"content": "Hi", "from_language": "en", "to_language": "yo"}
    )

    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_chat_page_csp_allows_its_inline_ui_only(client):
    csp = client.get("/chat").headers["Content-Security-Policy"]

    assert "script-src 'self' 'unsafe-inline'" in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_docs_keep_working_without_csp(client):
    response = client.get("/docs")

    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers


def test_hsts_over_https():
    from fastapi.testclient import TestClient

    from main import app

    response = TestClient(app, base_url="https://testserver").get("/health")

    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"


def test_oversized_body_is_rejected(client):
    big = "a" * (config.MAX_REQUEST_BYTES + 1)

    response = client.post(
        "/v1/translate",
        content=big,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {
        "error": True,
        "message": "Request body too large",
        "status_code": 413,
    }


def test_oversized_chunked_body_is_rejected(client):
    chunk = b"a" * 65536
    chunks = (config.MAX_REQUEST_BYTES // len(chunk)) + 2

    def body():
        for _ in range(chunks):
            yield chunk

    response = client.post(
        "/v1/translate", content=body(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413


def test_normal_body_is_accepted(client):
    response = client.post(
        "/v1/translate", json={"content": "Hi", "from_language": "en", "to_language": "en"}
    )

    assert response.status_code == 200


async def _chat_owners(monkeypatch, peer: str, forwarded_for: str):
    """Run /v1/chat through uvicorn's proxy middleware and return the owners it used"""
    from main import app

    owners = []

    async def fake_create(owner):
        owners.append(owner)
        return "test-conversation"

    async def fake_append(*args, **kwargs):
        return None

    async def fake_run_agent(*args, **kwargs):
        return {"answer": "ok", "language": "en", "reply_language": "en", "steps": []}

    monkeypatch.setattr(conversations, "create", fake_create)
    monkeypatch.setattr(conversations, "append", fake_append)
    monkeypatch.setattr("routes.chat.run_agent", fake_run_agent)

    proxy = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")
    transport = httpx.ASGITransport(app=proxy, client=(peer, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.post(
            "/v1/chat",
            json={"message": "Hi", "language": "en"},
            headers={"X-Forwarded-For": forwarded_for},
        )

    assert response.status_code == 200
    return owners


async def test_trusted_proxy_resolves_the_forwarded_client(monkeypatch):
    owners = await _chat_owners(monkeypatch, "127.0.0.1", "203.0.113.9")

    assert owners == ["ip:203.0.113.9"]


async def test_untrusted_peer_cannot_spoof_forwarded_for(monkeypatch):
    owners = await _chat_owners(monkeypatch, "198.51.100.7", "203.0.113.9")

    assert owners == ["ip:198.51.100.7"]
