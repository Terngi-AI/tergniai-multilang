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

Free text in a record (source, translation, correction) is redacted before it is stored:
e-mails, URLs, phone numbers and long ID numbers become [EMAIL], [URL], [PHONE] and [ID], so
raw personal data never reaches the JSONL file or Redis. Records older than
FEEDBACK_RETENTION_DAYS are deleted (#141).
"""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import config
from services import pii, usage
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


# Record fields that hold user-written text and are redacted before storage
TEXT_FIELDS = ("source_text", "translated_text", "correction")


def redact_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Copy of a record with personal data in its text fields replaced by labels"""
    redacted = dict(record)
    for field in TEXT_FIELDS:
        value = redacted.get(field)
        if isinstance(value, str):
            redacted[field] = pii.redact(value)
    return redacted


def _expired(record: Dict[str, Any], cutoff: datetime) -> bool:
    """Whether a record was created before the cutoff (unreadable dates count as expired)"""
    try:
        created = datetime.fromisoformat(str(record.get("created_at")))
    except ValueError:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created < cutoff


def _cutoff() -> Optional[datetime]:
    days = config.FEEDBACK_RETENTION_DAYS
    return datetime.now(UTC) - timedelta(days=days) if days > 0 else None


def _line_expired(line: Any, cutoff: datetime) -> bool:
    try:
        record = json.loads(line)
    except (TypeError, ValueError):
        return True
    return not isinstance(record, dict) or _expired(record, cutoff)


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


def _prune_file(path: Path, cutoff: datetime) -> None:
    """Rewrite the file without expired records (records are appended oldest first)"""
    if not path.exists():
        return
    lines = _read_file(path)
    kept = [line for line in lines if not _line_expired(line, cutoff)]
    if len(kept) == len(lines):
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.writelines(f"{line}\n" for line in kept)
    temporary.replace(path)


async def _prune_redis(redis: Any, cutoff: datetime) -> None:
    """Drop expired records from the head of the list (records are appended oldest first)"""
    while True:
        oldest = await redis.lindex(_redis_key(), 0)
        if oldest is None or not _line_expired(oldest, cutoff):
            return
        await redis.lpop(_redis_key())


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
    """Store one feedback record (redacted) and return its generated id"""
    feedback_id = uuid.uuid4().hex
    stored = {
        "id": feedback_id,
        "created_at": datetime.now(UTC).isoformat(),
        **redact_record(record),
    }
    cutoff = _cutoff()
    line = json.dumps(stored, ensure_ascii=False)
    limit = config.FEEDBACK_MAX_RECORDS

    if using_redis():
        try:
            redis = get_redis()
            if cutoff is not None:
                await _prune_redis(redis, cutoff)
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
            if cutoff is not None:
                await asyncio.to_thread(_prune_file, path, cutoff)
            await asyncio.to_thread(_append_file, path, line, limit)
    except FeedbackFull:
        raise
    except OSError as e:
        raise FeedbackError(str(e)) from e
    return feedback_id


async def load_records() -> List[Dict[str, Any]]:
    """
    Read every stored record within the retention period, oldest first

    Used by the evaluation export script. Expired records still on disk (nothing has been
    appended since they expired) are skipped.
    """
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

    cutoff = _cutoff()
    records: List[Dict[str, Any]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(record, dict) and (cutoff is None or not _expired(record, cutoff)):
            records.append(record)
    return records


def clear() -> None:
    """Remove the local file and the limits (tests only; Redis data is left untouched)"""
    limits_store.clear()
    if using_redis():
        return
    Path(config.FEEDBACK_FILE).unlink(missing_ok=True)
