"""
Append-only storage for opt-in translation feedback

Records are written either to Redis (when REDIS_URL is set) or to a JSONL file. Feedback is
never updated or deleted by the API. Callers must explicitly consent before anything is
stored.

API keys, IP addresses and other client identifiers are never part of a record. A record
made with an API key carries a `submitter` label: a keyed one-way hash of the key, used only
for feedback, so junk from one key can be filtered out without revealing or linking the key.

Each caller may store FEEDBACK_PER_KEY_PER_DAY records per UTC day, and exact duplicates
(same source, translation and rating from the same caller on the same day) are ignored (#140).
"""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from services import usage
from services.identifiers import keyed_hash
from services.store import StoreError, get_redis, make_store, using_redis

logger = logging.getLogger(__name__)

_file_lock = asyncio.Lock()


class FeedbackError(Exception):
    """Feedback storage could not be reached"""


class FeedbackFull(FeedbackError):
    """The feedback store reached FEEDBACK_MAX_RECORDS and cannot accept more"""


# Per-caller daily counters and duplicate fingerprints; entries outlive their UTC day
limits_store = make_store("feedback-limits", config.USAGE_MAX_ITEMS, 2 * 86400)


class Admission(Enum):
    """Whether a feedback record may be stored"""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    LIMITED = "limited"


def submitter_label(caller: str) -> str:
    """Keyed one-way label for a caller, used only for feedback (never the raw identifier)"""
    return keyed_hash(f"terngi-feedback:{caller}")[:16]


def fingerprint(record: Dict[str, Any]) -> str:
    """What makes two records duplicates: the same source, translation and rating"""
    parts = [record.get("source_text"), record.get("translated_text"), record.get("rating")]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:16]


async def admit(caller: str, record: Dict[str, Any]) -> Admission:
    """
    Count one record against the caller's daily limit, unless it is a duplicate

    A duplicate or a record over the limit leaves the counter unchanged. If the limits store
    is unavailable the record is accepted (fail open), like the usage counters.
    """
    limit = config.FEEDBACK_PER_KEY_PER_DAY
    if limit <= 0:
        return Admission.ACCEPTED

    digest = fingerprint(record)
    outcome = Admission.ACCEPTED

    def mutator(current: Optional[Any]) -> Optional[Dict[str, Any]]:
        nonlocal outcome
        seen = current.get("seen", []) if isinstance(current, dict) else []
        seen = [item for item in seen if isinstance(item, str)]
        if digest in seen:
            outcome = Admission.DUPLICATE
            return None
        if len(seen) >= limit:
            outcome = Admission.LIMITED
            return None
        return {"seen": [*seen, digest]}

    try:
        await limits_store.update(f"{usage.today()}:{submitter_label(caller)}", mutator)
    except StoreError:
        logger.warning("Feedback limits unavailable; accepting the record", exc_info=True)
        return Admission.ACCEPTED
    return outcome


async def release(caller: str, record: Dict[str, Any]) -> None:
    """Undo admit() when the record could not be stored, so a retry is not a duplicate"""
    if config.FEEDBACK_PER_KEY_PER_DAY <= 0:
        return
    digest = fingerprint(record)

    def mutator(current: Optional[Any]) -> Optional[Dict[str, Any]]:
        seen = current.get("seen", []) if isinstance(current, dict) else []
        if digest not in seen:
            return None
        return {"seen": [item for item in seen if item != digest]}

    try:
        await limits_store.update(f"{usage.today()}:{submitter_label(caller)}", mutator)
    except StoreError:
        logger.warning("Feedback limits unavailable; could not release a record", exc_info=True)


def _redis_key() -> str:
    return f"{config.REDIS_PREFIX}feedback"


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def _append_file(path: Path, line: str, max_records: int) -> None:
    if max_records > 0 and _count_lines(path) >= max_records:
        raise FeedbackFull("feedback storage is full")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.write("\n")


def _read_file(path: Path) -> List[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return handle.read().splitlines()


async def append(record: Dict[str, Any]) -> str:
    """Store one feedback record and return its generated id"""
    feedback_id = uuid.uuid4().hex
    stored = {
        "id": feedback_id,
        "created_at": datetime.now(UTC).isoformat(),
        **record,
    }
    line = json.dumps(stored, ensure_ascii=False)
    limit = config.FEEDBACK_MAX_RECORDS

    if using_redis():
        try:
            redis = get_redis()
            if limit > 0:
                # Append and trim keep the newest records without an unbounded list
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.rpush(_redis_key(), line)
                    pipe.ltrim(_redis_key(), -limit, -1)
                    await pipe.execute()
            else:
                await redis.rpush(_redis_key(), line)
        except Exception as e:
            raise FeedbackError(str(e)) from e
        return feedback_id

    path = Path(config.FEEDBACK_FILE)
    try:
        async with _file_lock:
            await asyncio.to_thread(_append_file, path, line, limit)
    except FeedbackFull:
        raise
    except OSError as e:
        raise FeedbackError(str(e)) from e
    return feedback_id


async def load_records() -> List[Dict[str, Any]]:
    """Read every stored record, oldest first (used by the evaluation export script)"""
    if using_redis():
        try:
            lines = await get_redis().lrange(_redis_key(), 0, -1)
        except Exception as e:
            raise FeedbackError(str(e)) from e
    else:
        try:
            lines = await asyncio.to_thread(_read_file, Path(config.FEEDBACK_FILE))
        except OSError as e:
            raise FeedbackError(str(e)) from e

    records: List[Dict[str, Any]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def clear() -> None:
    """Remove the local file and the limits (tests only; Redis data is left untouched)"""
    limits_store.clear()
    if using_redis():
        return
    Path(config.FEEDBACK_FILE).unlink(missing_ok=True)
