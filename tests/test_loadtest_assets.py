"""Smoke tests for the load-test upstream mock (issue #44)."""

from fastapi.testclient import TestClient

from loadtest.mock_upstream import app

client = TestClient(app)


def test_translate_response_shape():
    response = client.post(
        "/translate",
        params={"to": "yo"},
        json=[{"text": "Hello"}, {"text": "Thank you"}],
    )

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["translations"][0]["text"].startswith("mock[yo]:")


def test_detect_response_shape():
    response = client.post("/detect", json=[{"text": "Hello"}])

    assert response.status_code == 200
    assert response.json()[0]["language"] == "en"


def test_chat_completion_response_shape():
    response = client.post(
        "/openai/v1/chat/completions",
        json={"model": "loadtest", "messages": [{"role": "user", "content": "Hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"]


def test_morena_completion_response_shape():
    response = client.post("/morena/completion", json={"prompt": "Hello"})

    assert response.status_code == 200
    assert response.json()["content"]
