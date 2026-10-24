"""Tests for Unicode NFC normalisation (#27 Part 1)."""

import json
import unicodedata

import httpx
import respx

import config
import models
from services.text import normalize_text

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
DETECT_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/detect"

COMPOSED = "Yorùbá"
DECOMPOSED = unicodedata.normalize("NFD", COMPOSED)
REPLY = "Báwo ni"


def azure_translations(*texts: str) -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": text}]} for text in texts])


def test_normalize_text_and_request_models():
    assert DECOMPOSED != COMPOSED
    assert normalize_text(DECOMPOSED) == COMPOSED

    assert (
        models.TranslationRequest(content=DECOMPOSED, from_language="yo", to_language="en").content
        == COMPOSED
    )
    assert models.ChatRequest(message=DECOMPOSED).message == COMPOSED
    assert models.MemoryMessage(role="user", content=DECOMPOSED).content == COMPOSED


def test_request_is_normalised_before_length_validation():
    # NFD is longer than NFC, so this value only fits after normalisation.
    content = "a" * (config.MAX_CONTENT_LENGTH - 1) + unicodedata.normalize("NFD", "é")
    assert len(content) > config.MAX_CONTENT_LENGTH

    parsed = models.TranslationRequest(content=content, from_language="yo", to_language="en")

    assert len(parsed.content) == config.MAX_CONTENT_LENGTH
    assert parsed.content.endswith("é")


@respx.mock
def test_nfc_and_nfd_inputs_share_cache_and_output_is_nfc(client):
    route = respx.post(TRANSLATE_URL).mock(
        return_value=azure_translations(unicodedata.normalize("NFD", REPLY))
    )

    composed = client.post(
        "/v1/translate",
        json={"content": COMPOSED, "from_language": "yo", "to_language": "en"},
    )
    decomposed = client.post(
        "/v1/translate",
        json={"content": DECOMPOSED, "from_language": "yo", "to_language": "en"},
    )

    assert composed.status_code == 200
    assert decomposed.status_code == 200
    assert composed.json()["original_text"] == COMPOSED
    assert decomposed.json()["original_text"] == COMPOSED
    assert composed.json()["translated_text"] == REPLY
    assert decomposed.json()["translated_text"] == REPLY
    assert route.call_count == 1
    assert json.loads(route.calls[0].request.content) == [{"text": COMPOSED}]


@respx.mock
def test_batch_inputs_are_nfc_before_the_provider(client):
    route = respx.post(TRANSLATE_URL).mock(
        return_value=azure_translations(unicodedata.normalize("NFD", REPLY), "Igbo")
    )

    response = client.post(
        "/v1/translate/batch",
        json={"texts": [DECOMPOSED, "Igbo"], "from_language": "yo", "to_language": "en"},
    )

    assert response.status_code == 200
    assert response.json()["translations"] == [REPLY, "Igbo"]
    assert json.loads(route.calls.last.request.content) == [
        {"text": COMPOSED},
        {"text": "Igbo"},
    ]


@respx.mock
def test_detection_normalises_before_the_provider(client):
    route = respx.post(DETECT_URL).mock(
        return_value=httpx.Response(200, json=[{"language": "yo", "score": 0.98}])
    )

    response = client.post("/v1/detect", json={"content": DECOMPOSED})

    assert response.status_code == 200
    assert response.json()["language"] == "yo"
    assert json.loads(route.calls.last.request.content) == [{"text": COMPOSED}]
