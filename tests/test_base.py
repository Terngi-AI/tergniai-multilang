"""
Tests for the base routes
"""


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "en" in response.json()["supported_languages"]


def test_languages(client):
    response = client.get("/v1/languages")
    assert response.status_code == 200
    assert {"en", "fr", "yo", "ha", "ig", "pcm", "sw", "zu", "nr"} <= set(
        response.json()["languages"]
    )
    languages = response.json()["languages"]
    for code in ["zh-Hans", "ar", "pl", "nl", "es", "ga", "ja", "hi", "am", "wo"]:
        assert code in languages
    assert len(languages) > 80


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
