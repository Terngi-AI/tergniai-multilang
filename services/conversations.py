"""
Server-side conversation memory for /v1/chat

Conversations live in memory (per process) and expire after CONVERSATION_TTL_SECONDS of
inactivity. Each one belongs to the client that created it (API key or IP address).
"""

import hashlib
import uuid
from typing import Dict, List, Optional

import config
from services.cache import TTLCache

Message = Dict[str, str]

_store = TTLCache(max_items=config.CONVERSATION_MAX_ITEMS, ttl=config.CONVERSATION_TTL_SECONDS)


def _owner_hash(owner: str) -> str:
    """Store a hash of the owner so API keys are never kept in memory twice"""
    return hashlib.sha256(owner.encode()).hexdigest()


def create(owner: str) -> str:
    """Start a conversation and return its ID"""
    conversation_id = uuid.uuid4().hex
    _store.set(conversation_id, {"owner": _owner_hash(owner), "messages": []})
    return conversation_id


def get(conversation_id: str, owner: str) -> Optional[List[Message]]:
    """Return the conversation's messages, or None if it doesn't exist or isn't the owner's"""
    entry = _store.get(conversation_id)
    if entry is None or entry["owner"] != _owner_hash(owner):
        return None
    return list(entry["messages"])


def append(conversation_id: str, owner: str, *messages: Message) -> None:
    """Add messages, keeping only the most recent CONVERSATION_MAX_MESSAGES"""
    entry = _store.get(conversation_id)
    if entry is None or entry["owner"] != _owner_hash(owner):
        return
    entry["messages"] = (entry["messages"] + list(messages))[-config.CONVERSATION_MAX_MESSAGES :]
    _store.set(conversation_id, entry)  # refreshes the expiry


def delete(conversation_id: str, owner: str) -> bool:
    """Delete a conversation; returns False if it doesn't exist or isn't the owner's"""
    if get(conversation_id, owner) is None:
        return False
    _store.delete(conversation_id)
    return True


def clear() -> None:
    _store.clear()
