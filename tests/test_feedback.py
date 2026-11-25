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

    assert client.post("/v1/feedback", json=payload(source_text="One")).status_code == 200
    assert client.post("/v1/feedback", json=payload(source_text="Two")).status_code == 200

    full = client.post("/v1/feedback", json=payload(source_text="Three"))

    assert full.status_code == 507
    assert full.json()["code"] == "insufficient_storage"
    assert len(stored(path)) == 2

    # 0 disables the cap for an operator who rotates the file themselves
    monkeypatch.setattr(config, "FEEDBACK_MAX_RECORDS", 0)
    assert client.post("/v1/feedback", json=payload(source_text="Four")).status_code == 200
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


# --- Per-key daily limit and duplicates (#140) ---


def test_each_key_has_a_daily_feedback_limit(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "API_KEYS", ["key-one", "key-two"])
    monkeypatch.setattr(config, "FEEDBACK_PER_KEY_PER_DAY", 2)
    one, two = {"X-API-Key": "key-one"}, {"X-API-Key": "key-two"}

    for text in ("A", "B"):
        response = client.post("/v1/feedback", json=payload(source_text=text), headers=one)
        assert response.status_code == 200

    limited = client.post("/v1/feedback", json=payload(source_text="C"), headers=one)

    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert 1 <= int(limited.headers["Retry-After"]) <= 86400
    # Another key is not affected by the first one's limit
    other = client.post("/v1/feedback", json=payload(source_text="C"), headers=two)
    assert other.status_code == 200
    assert [r["source_text"] for r in stored(path)] == ["A", "B", "C"]


def test_duplicate_feedback_is_ignored_and_not_counted(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "FEEDBACK_PER_KEY_PER_DAY", 2)

    assert client.post("/v1/feedback", json=payload()).json() == {"status": "stored"}
    for _ in range(3):
        repeat = client.post("/v1/feedback", json=payload())
        assert repeat.status_code == 200
        assert repeat.json() == {"status": "duplicate"}

    # A different rating of the same translation is new feedback, and still within the limit
    assert client.post("/v1/feedback", json=payload(rating="bad")).json() == {"status": "stored"}
    assert len(stored(path)) == 2


def test_records_carry_a_feedback_only_label_for_the_key(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "API_KEYS", ["key-one", "key-two"])

    client.post("/v1/feedback", json=payload(source_text="A"), headers={"X-API-Key": "key-one"})
    client.post("/v1/feedback", json=payload(source_text="B"), headers={"X-API-Key": "key-one"})
    client.post("/v1/feedback", json=payload(source_text="C"), headers={"X-API-Key": "key-two"})

    labels = [record["submitter"] for record in stored(path)]
    assert labels[0] == labels[1] != labels[2]
    assert all(len(label) == 16 for label in labels)
    text = path.read_text(encoding="utf-8")
    assert "key-one" not in text and "key-two" not in text
    # Not the usage label either, so feedback can't be linked to usage metrics
    from services import usage

    assert usage.key_label("key-one") not in labels


def test_without_api_keys_records_have_no_submitter(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))

    client.post("/v1/feedback", json=payload())

    assert "submitter" not in stored(path)[0]


def test_feedback_that_could_not_be_stored_can_be_sent_again(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "FEEDBACK_MAX_RECORDS", 1)

    assert client.post("/v1/feedback", json=payload(source_text="A")).status_code == 200
    assert client.post("/v1/feedback", json=payload(source_text="B")).status_code == 507

    # The operator makes room; the same feedback is stored, not reported as a duplicate
    monkeypatch.setattr(config, "FEEDBACK_MAX_RECORDS", 0)
    retry = client.post("/v1/feedback", json=payload(source_text="B"))
    assert retry.json() == {"status": "stored"}


def test_feedback_limit_can_be_disabled(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "FEEDBACK_PER_KEY_PER_DAY", 0)

    for _ in range(3):
        assert client.post("/v1/feedback", json=payload()).json() == {"status": "stored"}
    assert len(stored(path)) == 3


async def test_feedback_limits_fail_open_when_storage_is_down(monkeypatch):
    async def broken(*_args, **_kwargs):
        raise store.StoreError("down")

    monkeypatch.setattr(feedback.limits_store, "update", broken)

    assert await feedback.admit("key:abc", payload()) is feedback.Admission.ACCEPTED
