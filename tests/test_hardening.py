"""
Tests for security headers and the request body size limit
"""

import config
import middleware


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
