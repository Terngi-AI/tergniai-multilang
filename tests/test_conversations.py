"""
Tests for conversation memory: concurrent appends must not lose a turn
"""

import asyncio

import fakeredis
import pytest

import config
from services import conversations, store


@pytest.mark.asyncio
async def test_memory_append_keeps_both_concurrent_turns():
    conversations.clear()
    conversation_id = await conversations.create("owner")

    await asyncio.gather(
        conversations.append(conversation_id, "owner", {"role": "user", "content": "one"}),
        conversations.append(conversation_id, "owner", {"role": "user", "content": "two"}),
    )
    messages = await conversations.get(conversation_id, "owner")

    assert [message["content"] for message in messages] == ["one", "two"]


@pytest.mark.asyncio
async def test_append_trims_history_to_the_character_budget(monkeypatch):
    monkeypatch.setattr(config, "CONVERSATION_MAX_CHARS", 12)
    conversations.clear()
    conversation_id = await conversations.create("owner")

    for text in ["one", "two", "three"]:
        await conversations.append(
            conversation_id,
            "owner",
            {"role": "user", "content": text},
            {"role": "assistant", "content": "ok"},
        )

    stored = await conversations._store.get(conversation_id)
    contents = [message["content"] for message in stored["messages"]]
    assert contents == ["two", "ok", "three", "ok"]
    assert sum(len(content) for content in contents) == 12

    messages = await conversations.get(conversation_id, "owner")
    assert [message["content"] for message in messages] == contents


@pytest.mark.asyncio
async def test_redis_append_keeps_both_concurrent_turns():
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    store.set_redis(fake)
    redis_store = store.RedisStore("conversation", config.CONVERSATION_TTL_SECONDS)

    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(conversations, "_store", redis_store)
            conversation_id = await conversations.create("owner")
            await asyncio.gather(
                conversations.append(conversation_id, "owner", {"role": "user", "content": "one"}),
                conversations.append(conversation_id, "owner", {"role": "user", "content": "two"}),
            )
            messages = await conversations.get(conversation_id, "owner")
    finally:
        store.set_redis(None)

    assert [message["content"] for message in messages] == ["one", "two"]
