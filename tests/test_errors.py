"""
Tests for the JSON error envelope (routing errors, HTTP errors and unhandled 500s)
"""

import httpx
import respx
from fastapi import HTTPException
from fastapi.testclient import TestClient

import config
import main
import middleware


def test_unknown_route_returns_json_envelope(client):
    response = client.get("/does/not/exist", headers={"X-Request-ID": "req-404"})

    assert response.status_code == 404
    assert response.json() == {
        "error": True,
        "message": "Not Found",
        "code": "not_found",
        "status_code": 404,
    }
    assert response.headers["X-Request-ID"] == "req-404"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == middleware.API_CSP


def test_method_not_allowed_keeps_allow_header(client):
    response = client.request("DELETE", "/health")

    assert response.status_code == 405
    assert response.json()["error"] is True
    assert response.json()["code"] == "method_not_allowed"
    assert response.json()["status_code"] == 405
    assert "GET" in response.headers["Allow"]


def test_http_exception_headers_are_preserved():
    async def teapot():
        raise HTTPException(status_code=418, detail="short and stout", headers={"X-Tea": "pot"})

    main.app.add_api_route("/__test_teapot", teapot)
    response = TestClient(main.app).get("/__test_teapot")

    assert response.status_code == 418
    assert response.json()["message"] == "short and stout"
    assert response.json()["code"] == "http_error"
    assert response.headers["X-Tea"] == "pot"
    assert response.headers["X-Request-ID"]


def test_unhandled_exception_returns_json_not_plain_text():
    async def boom():
        raise RuntimeError("do not leak this")

    main.app.add_api_route("/__test_boom", boom)
    client = TestClient(main.app, raise_server_exceptions=False)

    response = client.get("/__test_boom", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": True,
        "message": "Internal server error",
        "code": "internal_error",
        "status_code": 500,
    }
    assert "do not leak this" not in response.text
    assert response.headers["X-Request-ID"] == "req-500"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == middleware.API_CSP


@respx.mock
def test_malformed_detection_result_returns_json_error(client):
    respx.post(config.AZURE_TRANSLATOR_ENDPOINT + "/detect").mock(
        return_value=httpx.Response(200, json=[{"language": {"unexpected": True}, "score": 0.9}])
    )

    response = client.post("/v1/detect", json={"content": "Hello"})

    assert response.status_code == 502
    assert response.json()["error"] is True
    assert response.json()["code"] == "upstream_error"
    assert response.json()["status_code"] == 502
