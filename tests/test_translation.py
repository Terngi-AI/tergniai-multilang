"""
Tests for the translation route and Azure Translator service
"""

import httpx
import respx

import config

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"


def azure_ok(text: str) -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": text, "to": "yo"}]}])


@respx.mock
def test_translate_success(client):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_ok("Bawo ni"))

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "translated_text": "Bawo ni",
        "from_language": "en",
        "to_language": "yo",
        "original_text": "Hello",
    }
    assert route.called
    request = route.calls.last.request
    assert request.headers["Ocp-Apim-Subscription-Key"] == config.AZURE_TRANSLATOR_KEYS[0]


@respx.mock
def test_translate_same_language_skips_azure(client):
    route = respx.post(TRANSLATE_URL)

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "en"},
    )

    assert response.status_code == 200
    assert response.json()["translated_text"] == "Hello"
    assert not route.called


def test_translate_unsupported_language(client):
    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "tlh-Latn"},
    )

    assert response.status_code == 400
    assert response.json()["error"] is True


def test_translate_rejects_empty_content(client):
    response = client.post(
        "/v1/translate",
        json={"content": "", "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 422


def test_translate_rejects_oversized_content(client):
    response = client.post(
        "/v1/translate",
        json={
            "content": "a" * (config.MAX_CONTENT_LENGTH + 1),
            "from_language": "en",
            "to_language": "yo",
        },
    )

    assert response.status_code == 422


@respx.mock
def test_translate_upstream_error_is_not_leaked(client):
    respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(401, text="secret upstream detail"))

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 502
    assert "secret upstream detail" not in response.text


@respx.mock
def test_translate_upstream_timeout(client):
    respx.post(TRANSLATE_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 502


@respx.mock
def test_translate_malformed_upstream_response(client):
    respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(200, json=[]))

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 502


def test_translate_without_key_returns_503(client, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", [])

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 503


@respx.mock
def test_azure_rotates_to_next_key_when_one_is_revoked(client, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", ["revoked-key", "good-key"])
    route = respx.post(TRANSLATE_URL).mock(
        side_effect=lambda request: (
            httpx.Response(401)
            if request.headers["Ocp-Apim-Subscription-Key"] == "revoked-key"
            else httpx.Response(200, json=[{"translations": [{"text": "Bawo ni"}]}])
        )
    )

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "yo"},
    )

    assert response.json()["translated_text"] == "Bawo ni"
    assert route.call_count == 2


@respx.mock
def test_azure_all_keys_rejected_returns_502(client, monkeypatch):
    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", ["k1", "k2"])
    respx.post(TRANSLATE_URL).mock(return_value=httpx.Response(429))

    response = client.post(
        "/v1/translate",
        json={"content": "Hello", "from_language": "en", "to_language": "yo"},
    )

    assert response.status_code == 502
