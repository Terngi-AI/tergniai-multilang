"""
Server-side conversation memory for /v1/chat

Conversations are kept in memory (per process) or, with REDIS_URL set, in Redis so every
replica shares them and they survive restarts. They expire after CONVERSATION_TTL_SECONDS of
inactivity. Each one belongs to the client that created it (API key or IP address).
"""

import hashlib
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import config
from services.store import StoreError, make_store

Message = Dict[str, str]

_store = make_store("conversation", config.CONVERSATION_MAX_ITEMS, config.CONVERSATION_TTL_SECONDS)


def _owner_hash(owner: str) -> str:
    """Store a hash of the owner so API keys are never kept in memory twice"""
    return hashlib.sha256(owner.encode()).hexdigest()


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
    return conversation_id


async def get(conversation_id: str, owner: str) -> Optional[List[Message]]:
    """Return the conversation's messages, or None if it doesn't exist or isn't the owner's"""
    entry = await _load(conversation_id)
    if entry is None or entry["owner"] != _owner_hash(owner):
        return None
    return list(entry["messages"])


async def append(conversation_id: str, owner: str, *messages: Message) -> None:
    """Add messages, keeping only the most recent CONVERSATION_MAX_MESSAGES"""
    entry = await _load(conversation_id)
    if entry is None or entry["owner"] != _owner_hash(owner):
        return
    entry["messages"] = (entry["messages"] + list(messages))[-config.CONVERSATION_MAX_MESSAGES :]
    await _save(conversation_id, entry)


async def delete(conversation_id: str, owner: str) -> bool:
    """Delete a conversation; returns False if it doesn't exist or isn't the owner's"""
    if await get(conversation_id, owner) is None:
        return False
    try:
        await _store.delete(conversation_id)
    except StoreError as e:
        raise _unavailable(e) from e
    return True


def clear() -> None:
    _store.clear()
