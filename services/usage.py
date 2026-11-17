"""
Per-API-key usage tracking and optional daily request quotas

Requests, upstream calls and provider-reported tokens are counted per UTC day and per
API key. The key itself is never stored: counters use a short SHA-256 label. Without
REDIS_URL the counters live in each process; with it every replica shares them.

Usage accounting must never break a request. If the store is unavailable, requests are
allowed (fail open) and the counters are skipped.
"""

import hashlib
import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import Any, Callable, Dict, Optional, Tuple

import config
import metrics
from services.store import StoreError, make_store

logger = logging.getLogger(__name__)

usage_store = make_store("usage", config.USAGE_MAX_ITEMS, config.USAGE_TTL_SECONDS)

# API-key label for the request being handled; set by middleware.usage_limits
_current_key: ContextVar[Optional[str]] = ContextVar("usage_key", default=None)


@dataclass(frozen=True)
class Usage:
    """Counters for one API key on one UTC day"""

    requests: int = 0
    upstream_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self) -> Dict[str, int]:
        return {
            "requests": self.requests,
            "upstream_calls": self.upstream_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Usage":
        """Read a stored entry, tolerating missing fields and old or edited values"""
        if not isinstance(data, dict):
            return cls()

        def count(name: str) -> int:
            value = data.get(name, 0)
            return value if isinstance(value, int) and value >= 0 else 0

        return cls(
            requests=count("requests"),
            upstream_calls=count("upstream_calls"),
            prompt_tokens=count("prompt_tokens"),
            completion_tokens=count("completion_tokens"),
        )


EMPTY = Usage()


def key_label(api_key: str) -> str:
    """Short, stable label used for storage and metrics; the key cannot be recovered"""
    return hashlib.sha256(f"terngi-usage:{api_key}".encode()).hexdigest()[:16]


def begin(label: Optional[str]) -> None:
    """Set the API-key label for the current request"""
    _current_key.set(label)


def current_label() -> Optional[str]:
    """The API-key label for the current request, if usage is being tracked"""
    return _current_key.get()


def quota_for(api_key: Optional[str]) -> Optional[int]:
    """Daily request quota configured for this key, if any"""
    if not api_key or not config.API_KEYS:
        return None
    return config.API_KEY_QUOTAS.get(api_key)


def today() -> str:
    """Current UTC day, used as the usage window"""
    return datetime.now(UTC).date().isoformat()


def _entry_key(label: str, day: Optional[str] = None) -> str:
    return f"{day or today()}:{label}"


def _next_reset() -> datetime:
    now = datetime.now(UTC)
    return datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)


def seconds_until_tomorrow() -> int:
    """Seconds until the daily quota resets (next UTC midnight), at least one"""
    seconds = (_next_reset() - datetime.now(UTC)).total_seconds()
    return max(1, int(seconds + 0.999))


def reset_at() -> str:
    """When the daily quota resets, as an ISO-8601 UTC timestamp"""
    return _next_reset().isoformat().replace("+00:00", "Z")


def _count(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


async def _update(
    key: str, mutator: Callable[[Optional[Any]], Optional[Dict[str, int]]]
) -> Optional[Dict[str, int]]:
    """Apply one atomic counter update, failing open when storage is unavailable"""
    try:
        return await usage_store.update(key, mutator)
    except StoreError:
        logger.warning("Usage storage unavailable; counters were not saved", exc_info=True)
        return None


async def hit(label: str, quota: Optional[int] = None) -> Tuple[bool, Usage]:
    """
    Count one request and enforce an optional daily quota

    Returns:
        (allowed, usage after the request). A rejected request leaves the counter unchanged.
        If storage is unavailable the request is allowed and the counter is skipped.
    """
    allowed = True
    result = EMPTY

    def mutator(current: Optional[Any]) -> Optional[Dict[str, int]]:
        nonlocal allowed, result
        usage = Usage.from_dict(current)
        if quota is not None and usage.requests >= quota:
            allowed = False
            result = usage
            return None
        usage = replace(usage, requests=usage.requests + 1)
        result = usage
        return usage.as_dict()

    await _update(_entry_key(label), mutator)
    return allowed, result


async def record_upstream(prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """Count one upstream call and, when the provider returned them, its tokens"""
    label = _current_key.get()
    if label is None:
        return

    prompt_tokens = _count(prompt_tokens)
    completion_tokens = _count(completion_tokens)
    metrics.API_KEY_UPSTREAM_CALLS.labels(label).inc()
    if prompt_tokens:
        metrics.API_KEY_TOKENS.labels(label, "prompt").inc(prompt_tokens)
    if completion_tokens:
        metrics.API_KEY_TOKENS.labels(label, "completion").inc(completion_tokens)

    def mutator(current: Optional[Any]) -> Dict[str, int]:
        usage = Usage.from_dict(current)
        return replace(
            usage,
            upstream_calls=usage.upstream_calls + 1,
            prompt_tokens=usage.prompt_tokens + prompt_tokens,
            completion_tokens=usage.completion_tokens + completion_tokens,
        ).as_dict()

    await _update(_entry_key(label), mutator)


async def snapshot(label: str, day: Optional[str] = None) -> Usage:
    """Read the counters for `label` (today unless `day` is given)"""
    try:
        data = await usage_store.get(_entry_key(label, day))
    except StoreError:
        logger.warning("Usage storage unavailable; returning no usage", exc_info=True)
        return EMPTY
    return Usage.from_dict(data)
