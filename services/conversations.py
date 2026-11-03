"""
Server-side conversation memory for /v1/chat

Conversations are kept in memory (per process) or, with REDIS_URL set, in Redis so every
replica shares them and they survive restarts. They expire after CONVERSATION_TTL_SECONDS of
inactivity. Each one belongs to the client that created it (API key or IP address).
"""

import uuid
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException

import config
from services import identifiers
from services.store import StoreError, get_redis, make_store, using_redis

Message = Dict[str, str]

_store = make_store(
    "conversation",
    config.CONVERSATION_MAX_ITEMS,
    config.CONVERSATION_TTL_SECONDS,
    enforce_max_items=True,
)

# Per-owner index of conversation IDs: delete_all reads only this, so it never has to
# load every stored conversation to find the caller's ones (issue #121). In Redis it is
# one set per owner, refreshed with the conversations' TTL; in memory a plain set. Stale
# entries (an expired or evicted conversation) are harmless: delete_all skips anything
# that is gone or belongs to another owner.
_owner_index: Dict[str, Set[str]] = {}


def _owner_hash(owner: str) -> str:
    """
    Store a keyed hash of the owner so API keys are never kept in memory twice, and an
    IP address is never reversible from the stored key (plain SHA-256 of an IP is not)
    """
    return identifiers.keyed_hash(owner)


def _owner_index_key(owner_hash: str) -> str:
    """Redis key of the owner's conversation index (a set of conversation IDs)"""
    return f"{config.REDIS_PREFIX}conversation-owner:{owner_hash}"


async def _index_add(owner: str, conversation_id: str) -> None:
    """Remember that `owner` has a conversation, so delete_all can find it later"""
    if config.CONVERSATION_TTL_SECONDS <= 0:
        return  # nothing is persisted, so there is nothing to index
    if using_redis():
        try:
            key = _owner_index_key(_owner_hash(owner))
            async with get_redis().pipeline(transaction=True) as pipe:
                pipe.sadd(key, conversation_id)
                pipe.expire(key, config.CONVERSATION_TTL_SECONDS)
                await pipe.execute()
        except Exception as e:
            raise StoreError(str(e)) from e
    else:
        _owner_index.setdefault(_owner_hash(owner), set()).add(conversation_id)


async def _index_remove(owner: str, conversation_ids: List[str]) -> None:
    """Drop deleted conversations from `owner`'s index"""
    if config.CONVERSATION_TTL_SECONDS <= 0:
        return
    if using_redis():
        if conversation_ids:
            try:
                await get_redis().srem(_owner_index_key(_owner_hash(owner)), *conversation_ids)
            except Exception as e:
                raise StoreError(str(e)) from e
    else:
        members = _owner_index.get(_owner_hash(owner))
        if members:
            members.difference_update(conversation_ids)
            if not members:
                del _owner_index[_owner_hash(owner)]


async def _index_members(owner: str) -> List[str]:
    """The conversation IDs `owner` is indexed with"""
    if config.CONVERSATION_TTL_SECONDS <= 0:
        return []
    if using_redis():
        try:
            return sorted(await get_redis().smembers(_owner_index_key(_owner_hash(owner))))
        except Exception as e:
            raise StoreError(str(e)) from e
    return sorted(_owner_index.get(_owner_hash(owner)) or ())


def _limit_history(messages: List[Message]) -> List[Message]:
    """Keep the newest messages that fit in CONVERSATION_MAX_CHARS characters"""
    budget = config.CONVERSATION_MAX_CHARS
    if budget <= 0:
        return list(messages)

    kept: List[Message] = []
    total = 0
    for message in reversed(messages):
        size = len(message.get("content", ""))
        if kept and total + size > budget:
            break
        kept.append(message)
        total += size
    kept.reverse()

    # Do not start with an assistant reply whose question fell outside the budget
    while len(kept) > 1 and kept[0].get("role") == "assistant":
        kept.pop(0)
    return kept


def _unavailable(e: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail="Conversation storage is unavailable")


async def _load(conversation_id: str) -> Optional[Dict[str, Any]]:
    try:
        return await _store.get(conversation_id)
    except StoreError as e:
        raise _unavailable(e) from e


async def _save(conversation_id: str, entry: Dict[str, Any]) -> None:
    try:
        await _store.set(conversation_id, entry)  # also refreshes the expiry
    except StoreError as e:
        raise _unavailable(e) from e


async def create(owner: str) -> str:
    """Start a conversation and return its ID"""
    conversation_id = uuid.uuid4().hex
    await _save(conversation_id, {"owner": _owner_hash(owner), "messages": []})
    try:
        await _index_add(owner, conversation_id)
    except StoreError as e:
        raise _unavailable(e) from e
    return conversation_id


async def get(conversation_id: str, owner: str) -> Optional[List[Message]]:
    """Return the conversation's messages, or None if it doesn't exist or isn't the owner's"""
    entry = await _load(conversation_id)
    if entry is None or entry["owner"] != _owner_hash(owner):
        return None
    return _limit_history(list(entry["messages"]))


async def append(conversation_id: str, owner: str, *messages: Message) -> None:
    """Atomically add messages, keeping only the most recent CONVERSATION_MAX_MESSAGES"""
    owner_hash = _owner_hash(owner)

    def mutate(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if entry is None or entry.get("owner") != owner_hash:
            return None
        updated = dict(entry)
        combined = (list(entry.get("messages", [])) + list(messages))[
            -config.CONVERSATION_MAX_MESSAGES :
        ]
        updated["messages"] = _limit_history(combined)
        return updated

    try:
        await _store.update(conversation_id, mutate)
    except StoreError as e:
        raise _unavailable(e) from e


async def delete(conversation_id: str, owner: str) -> bool:
    """Delete a conversation; returns False if it doesn't exist or isn't the owner's"""
    if await get(conversation_id, owner) is None:
        return False
    try:
        await _store.delete(conversation_id)
        await _index_remove(owner, [conversation_id])
    except StoreError as e:
        raise _unavailable(e) from e
    return True


async def delete_all(owner: str) -> int:
    """
    Delete every conversation belonging to `owner`; returns how many were removed

    Reads only the owner's index, so the other callers' conversations are never loaded
    (issue #121). Conversations created before the index existed are not found here;
    they expire after CONVERSATION_TTL_SECONDS anyway.
    """
    owner_hash = _owner_hash(owner)
    try:
        conversation_ids = await _index_members(owner)
    except StoreError as e:
        raise _unavailable(e) from e

    deleted = 0
    for conversation_id in conversation_ids:
        entry = await _load(conversation_id)
        if entry is None or entry.get("owner") != owner_hash:
            continue
        try:
            await _store.delete(conversation_id)
        except StoreError as e:
            raise _unavailable(e) from e
        deleted += 1
    if conversation_ids:
        try:
            await _index_remove(owner, conversation_ids)
        except StoreError as e:
            raise _unavailable(e) from e
    return deleted


def clear() -> None:
    _store.clear()
    _owner_index.clear()
