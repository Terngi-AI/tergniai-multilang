"""Tests for opt-in translation feedback (issue #43)"""

import asyncio
import json

import fakeredis

import config
from scripts.export_feedback import build_records, write_jsonl
from services import feedback, store


def payload(**overrides):
    body = {
        "source_text": "Welcome to Terngi",
        "translated_text": "Ẹ káàbọ̀ sí Terngi",
        "from_language": "en",
        "to_language": "yo",
        "provider": "chat",
        "rating": "good",
        "consent": True,
    }
    body.update(overrides)
    return body


def stored(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_feedback_requires_consent(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(tmp_path / "feedback.jsonl"))

    response = client.post("/v1/feedback", json=payload(consent=False))

    assert response.status_code == 400
    assert not (tmp_path / "feedback.jsonl").exists()


def test_feedback_needs_the_api_key(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "API_KEYS", ["client-key"])
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(tmp_path / "feedback.jsonl"))

    response = client.post("/v1/feedback", json=payload())

    assert response.status_code == 401
    assert not (tmp_path / "feedback.jsonl").exists()


def test_feedback_is_appended_without_api_keys(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    headers = {"X-API-Key": "a-secret-that-must-not-be-stored"}

    first = client.post("/v1/feedback", json=payload(), headers=headers)
    second = client.post(
        "/v1/feedback",
        json=payload(rating="bad", correction="Ẹ káàbọ̀ Terngi"),
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json() == {"status": "stored"}
    assert second.status_code == 200
    records = stored(path)
    assert len(records) == 2
    assert records[0]["source_text"] == "Welcome to Terngi"
    assert records[1]["correction"] == "Ẹ káàbọ̀ Terngi"
    assert records[0]["consent"] is True
    assert records[0]["id"]
    assert records[0]["created_at"]
    assert "a-secret-that-must-not-be-stored" not in path.read_text(encoding="utf-8")


def test_bad_rating_without_correction_is_still_stored(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))

    response = client.post("/v1/feedback", json=payload(rating="bad"))

    assert response.status_code == 200
    assert stored(path)[0]["rating"] == "bad"


def test_file_storage_refuses_records_past_the_cap(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "FEEDBACK_MAX_RECORDS", 2)

    assert client.post("/v1/feedback", json=payload()).status_code == 200
    assert client.post("/v1/feedback", json=payload()).status_code == 200

    full = client.post("/v1/feedback", json=payload())

    assert full.status_code == 507
    assert full.json()["code"] == "insufficient_storage"
    assert len(stored(path)) == 2

    # 0 disables the cap for an operator who rotates the file themselves
    monkeypatch.setattr(config, "FEEDBACK_MAX_RECORDS", 0)
    assert client.post("/v1/feedback", json=payload()).status_code == 200
    assert len(stored(path)) == 3


def test_invalid_rating_is_rejected(client):
    response = client.post("/v1/feedback", json=payload(rating="maybe"))

    assert response.status_code == 422


def test_unsupported_language_is_rejected(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(tmp_path / "feedback.jsonl"))

    response = client.post("/v1/feedback", json=payload(to_language="tlh-Latn"))

    assert response.status_code == 400


def test_export_keeps_usable_references_and_consent():
    records = [
        {
            "source_text": "Hello",
            "translated_text": "Bawo ni",
            "from_language": "en",
            "to_language": "yo",
            "provider": "azure",
            "rating": "good",
            "consent": True,
        },
        {
            "source_text": "Thank you",
            "translated_text": "O ṣeun",
            "from_language": "en",
            "to_language": "yo",
            "provider": "azure",
            "rating": "bad",
            "correction": "Ẹ ṣé",
            "consent": True,
        },
        {
            "source_text": "Bad without correction",
            "translated_text": "wrong",
            "from_language": "en",
            "to_language": "yo",
            "provider": "azure",
            "rating": "bad",
            "consent": True,
        },
        {
            "source_text": "No consent",
            "translated_text": "not exported",
            "from_language": "en",
            "to_language": "yo",
            "provider": "azure",
            "rating": "good",
            "consent": False,
        },
    ]

    exported = build_records(records)

    assert exported == [
        {
            "source": "Hello",
            "reference": "Bawo ni",
            "from_language": "en",
            "to_language": "yo",
            "provider": "azure",
        },
        {
            "source": "Thank you",
            "reference": "Ẹ ṣé",
            "from_language": "en",
            "to_language": "yo",
            "provider": "azure",
        },
    ]


def test_export_writes_jsonl(tmp_path):
    output = tmp_path / "eval" / "feedback.jsonl"
    count = write_jsonl([{"source": "Hello", "reference": "Bawo ni"}], output)

    assert count == 1
    assert json.loads(output.read_text(encoding="utf-8"))["reference"] == "Bawo ni"


def test_chat_page_has_opt_in_feedback(client):
    page = client.get("/chat")

    assert page.status_code == 200
    # The UI script is an external file (CSP forbids inline scripts).
    assert 'src="/static/chat.js"' in page.text

    js = client.get("/static/chat.js")
    assert js.status_code == 200
    assert "Rate this reply" in js.text
    assert "may be stored and published" in js.text
    assert "/v1/feedback" in js.text


def test_feedback_storage_reads_back(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))

    assert client.post("/v1/feedback", json=payload()).status_code == 200

    records = asyncio.run(feedback.load_records())
    assert records[0]["rating"] == "good"


async def test_feedback_is_appended_to_redis(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    store.set_redis(fake)
    try:
        first = await feedback.append({"rating": "good", "consent": True})
        second = await feedback.append({"rating": "bad", "consent": True})
        lines = await fake.lrange(f"{config.REDIS_PREFIX}feedback", 0, -1)
        records = await feedback.load_records()
    finally:
        store.set_redis(None)

    assert [json.loads(line)["id"] for line in lines] == [first, second]
    assert [record["rating"] for record in records] == ["good", "bad"]


async def test_redis_storage_drops_the_oldest_records_at_the_cap(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    monkeypatch.setattr(config, "FEEDBACK_MAX_RECORDS", 2)
    store.set_redis(fake)
    try:
        ids = [await feedback.append({"rating": "good", "consent": True}) for _ in range(3)]
        lines = await fake.lrange(f"{config.REDIS_PREFIX}feedback", 0, -1)
    finally:
        store.set_redis(None)

    assert [json.loads(line)["id"] for line in lines] == ids[1:]
