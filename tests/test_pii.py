"""
Tests for personal-data handling: feedback redaction and retention (#141) and optional
masking before text reaches a provider (#142)
"""

import json
from datetime import UTC, datetime, timedelta

import fakeredis
import httpx
import pytest
import respx

import config
from services import feedback, pii, store
from tests.conftest import GROQ_URL

TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
CHAT_URL = GROQ_URL + "/chat/completions"
PHONE = "+234 803 123 4567"
REDIS_KEY = f"{config.REDIS_PREFIX}feedback"
EMAIL = "amina.yusuf@example.com"


def chat_reply(payload) -> httpx.Response:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def azure_reply(text: str) -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": text}]}])


def translate(client, content):
    return client.post(
        "/v1/translate", json={"content": content, "from_language": "en", "to_language": "yo"}
    )


# --- shared patterns ----------------------------------------------------------


def test_mask_and_unmask_round_trip():
    text = f"Call {PHONE} or mail {EMAIL}; again {PHONE}"

    masked, replacements = pii.mask(text)

    # E-mails and URLs are matched before phone numbers, so they are numbered first
    assert masked == "Call [[P2]] or mail [[P1]]; again [[P2]]"
    assert replacements == {"[[P1]]": EMAIL, "[[P2]]": PHONE}
    assert pii.unmask(masked, replacements) == text


def test_unmask_accepts_spaces_a_model_added():
    _, replacements = pii.mask(f"Call {PHONE}")

    assert pii.unmask("Pe [[ P1 ]]", replacements) == f"Pe {PHONE}"


def test_mask_never_reuses_a_placeholder_already_in_the_text():
    masked, replacements = pii.mask(f"Template [[P1]] for {PHONE}")

    assert masked == "Template [[P1]] for [[P2]]"
    assert pii.unmask(masked, replacements) == f"Template [[P1]] for {PHONE}"


def test_missing_lists_dropped_placeholders():
    _, replacements = pii.mask(f"{PHONE} {EMAIL}")

    assert pii.missing("only [[P1]]", replacements) == ["[[P2]]"]  # [[P2]] is the phone
    assert pii.missing("[[P2]] [[P1]]", replacements) == []


def test_text_without_personal_data_is_unchanged():
    assert pii.mask("Meet on 2026-10-25 at 10:30") == ("Meet on 2026-10-25 at 10:30", {})


# --- #141: feedback is redacted before it is stored ----------------------------


def feedback_payload(**overrides):
    body = {
        "source_text": f"Call me on {PHONE} or {EMAIL}",
        "translated_text": f"Pè mí ní {PHONE} tàbí {EMAIL}",
        "from_language": "en",
        "to_language": "yo",
        "provider": "chat",
        "rating": "bad",
        "correction": f"Ẹ pè mí ní {PHONE}",
        "consent": True,
    }
    body.update(overrides)
    return body


def test_feedback_is_redacted_before_it_reaches_the_file(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))

    assert client.post("/v1/feedback", json=feedback_payload()).status_code == 200

    raw = path.read_text(encoding="utf-8")
    assert "803" not in raw and "amina" not in raw
    record = json.loads(raw)
    assert record["source_text"] == "Call me on [PHONE] or [EMAIL]"
    assert record["translated_text"] == "Pè mí ní [PHONE] tàbí [EMAIL]"
    assert record["correction"] == "Ẹ pè mí ní [PHONE]"


async def test_feedback_is_redacted_before_it_reaches_redis(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    store.set_redis(fake)
    try:
        await feedback.append(feedback_payload())
        raw = await fake.lrange(REDIS_KEY, 0, -1)
    finally:
        store.set_redis(None)

    assert not any("803" in line or "amina" in line for line in raw)
    assert json.loads(raw[0])["source_text"] == "Call me on [PHONE] or [EMAIL]"


def test_redaction_does_not_break_duplicate_detection(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(tmp_path / "feedback.jsonl"))

    assert client.post("/v1/feedback", json=feedback_payload()).json()["status"] == "stored"
    assert client.post("/v1/feedback", json=feedback_payload()).json()["status"] == "duplicate"


def _old_record(days: int) -> str:
    created = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    return json.dumps({"id": f"old-{days}", "created_at": created, "consent": True})


def test_expired_feedback_is_deleted_on_the_next_append(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    path.write_text(_old_record(40) + "\n" + _old_record(5) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "FEEDBACK_RETENTION_DAYS", 30)

    assert client.post("/v1/feedback", json=feedback_payload()).status_code == 200

    ids = [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()]
    assert "old-40" not in ids
    assert "old-5" in ids
    assert len(ids) == 2


async def test_expired_feedback_is_not_exported(tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    path.write_text(_old_record(40) + "\n" + _old_record(5) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))
    monkeypatch.setattr(config, "FEEDBACK_RETENTION_DAYS", 30)

    records = await feedback.load_records()

    assert [record["id"] for record in records] == ["old-5"]


async def test_expired_feedback_is_deleted_from_redis(monkeypatch):
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(config, "REDIS_URL", "redis://fake")
    monkeypatch.setattr(config, "FEEDBACK_RETENTION_DAYS", 30)
    await fake.rpush(REDIS_KEY, _old_record(40), _old_record(5))
    store.set_redis(fake)
    try:
        new_id = await feedback.append({"rating": "good", "consent": True})
        raw = await fake.lrange(REDIS_KEY, 0, -1)
    finally:
        store.set_redis(None)

    assert [json.loads(line)["id"] for line in raw] == ["old-5", new_id]


def test_retention_off_keeps_old_records(client, tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    path.write_text(_old_record(4000) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "FEEDBACK_FILE", str(path))

    assert client.post("/v1/feedback", json=feedback_payload()).status_code == 200

    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


# --- #142: PII_MASKING ---------------------------------------------------------


@pytest.fixture
def masking(monkeypatch):
    monkeypatch.setattr(config, "PII_MASKING", True)


@respx.mock
def test_azure_sees_placeholders_and_the_caller_gets_the_number_back(client, masking):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_reply("Pè mí ní [[P1]]"))

    response = translate(client, f"Call me on {PHONE}")

    assert response.status_code == 200
    assert response.json()["translated_text"] == f"Pè mí ní {PHONE}"
    sent = route.calls.last.request.content.decode()
    assert "803" not in sent
    assert "[[P1]]" in sent


@respx.mock
def test_llm_sees_placeholders_and_is_told_to_keep_them(client, masking, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["groq"])
    route = respx.post(CHAT_URL).mock(
        return_value=chat_reply({"translations": ["Kọ sí [[P1]] tàbí pè [[P2]]"]})
    )

    response = translate(client, f"Write to {EMAIL} or call {PHONE}")

    assert response.json()["translated_text"] == f"Kọ sí {EMAIL} tàbí pè {PHONE}"
    body = json.loads(route.calls.last.request.content)
    assert "[[P1]]" in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"]) == {
        "texts": ["Write to [[P1]] or call [[P2]]"]
    }
    assert "803" not in route.calls.last.request.content.decode()


@respx.mock
def test_dropped_placeholder_falls_back_to_the_next_provider(client, masking, monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["azure", "groq"])
    respx.post(TRANSLATE_URL).mock(return_value=azure_reply("Pè mí"))
    llm = respx.post(CHAT_URL).mock(return_value=chat_reply({"translations": ["Pè mí ní [[P1]]"]}))

    response = translate(client, f"Call me on {PHONE}")

    assert response.status_code == 200
    assert response.json()["translated_text"] == f"Pè mí ní {PHONE}"
    assert llm.called


@respx.mock
def test_every_provider_dropping_a_placeholder_is_an_error(client, masking):
    respx.post(TRANSLATE_URL).mock(return_value=azure_reply("Pè mí"))

    response = translate(client, f"Call me on {PHONE}")

    assert response.status_code == 502
    assert "803" not in response.text


@respx.mock
def test_masking_is_off_by_default(client):
    route = respx.post(TRANSLATE_URL).mock(return_value=azure_reply("Pè mí"))

    translate(client, f"Call me on {PHONE}")

    assert "803" in route.calls.last.request.content.decode()


@respx.mock
def test_chat_reply_gets_masked_values_back(client, masking):
    route = respx.post(CHAT_URL).mock(return_value=chat_reply("Sure, I will call [[P1]]."))

    response = client.post(
        "/v1/converse",
        json={
            "content": "Please call me back",
            "from_language": "en",
            "to_language": "en",
            "memory_context": [{"role": "user", "content": f"My number is {PHONE}"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["response"] == f"Sure, I will call {PHONE}."
    body = json.loads(route.calls.last.request.content)
    assert body["messages"][1]["content"] == "My number is [[P1]]"
    assert "[[P1]]" in body["messages"][0]["content"]
    assert "803" not in route.calls.last.request.content.decode()
