"""
Retry helpers shared by upstream clients: Retry-After parsing and exponential backoff
"""

import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

import config

# Upstream responses worth retrying: throttling and transient server errors
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Return the Retry-After header (delta-seconds or HTTP-date) in seconds, if valid"""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def retry_delay(attempt: int, response: Optional[httpx.Response]) -> Optional[float]:
    """
    Seconds to wait before retry number `attempt` (0-based), or None to stop

    Uses the server's Retry-After when present, otherwise exponential backoff
    with full jitter. A Retry-After longer than UPSTREAM_RETRY_MAX_DELAY means
    retrying sooner would only be throttled again, so we give up instead.
    """
    if response is not None:
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            return retry_after if retry_after <= config.UPSTREAM_RETRY_MAX_DELAY else None
    ceiling = min(config.UPSTREAM_RETRY_MAX_DELAY, config.UPSTREAM_RETRY_BASE_DELAY * 2**attempt)
    return random.uniform(0, ceiling)  # noqa: S311 - jitter, not cryptography
