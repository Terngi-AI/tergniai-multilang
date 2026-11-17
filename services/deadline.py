"""
Request-scoped deadlines, upstream-attempt budgets and the request ID

The middleware starts a budget for every HTTP request. Services call `check()` between
steps, use `timeout()` for each upstream call, `sleep()` for backoff, and
`consume_attempt()` so retries and provider fallbacks share one cap. The request ID
also lives in a context variable here so service logs (e.g. upstream errors) can be
correlated with the request.
"""

import asyncio
import time
from contextvars import ContextVar
from typing import Optional

from fastapi import HTTPException

import config

_deadline: ContextVar[Optional[float]] = ContextVar("request_deadline", default=None)
_attempts: ContextVar[int] = ContextVar("request_attempts", default=0)
_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def begin(seconds: float):
    """Start a budget; seconds <= 0 disables both the deadline and the attempt cap"""
    expires = None if seconds <= 0 else time.monotonic() + seconds
    return _deadline.set(expires), _attempts.set(0)


def end(tokens) -> None:
    _deadline.reset(tokens[0])
    _attempts.reset(tokens[1])


def set_request_id(request_id: str):
    """Bind the request ID for the duration of the request (for log correlation)"""
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def request_id() -> Optional[str]:
    """The current request ID, or None outside a request (e.g. startup work)"""
    return _request_id.get()


def remaining() -> Optional[float]:
    expires = _deadline.get()
    if expires is None:
        return None
    return max(0.0, expires - time.monotonic())


def _exceeded() -> HTTPException:
    return HTTPException(
        status_code=504,
        detail="Request deadline exceeded",
        headers={"Retry-After": "1"},
    )


def check() -> None:
    """Raise 504 once the request's wall-clock budget is spent"""
    expires = _deadline.get()
    if expires is not None and time.monotonic() >= expires:
        raise _exceeded()


def timeout(default: float) -> float:
    """A per-attempt timeout that never outlives the request deadline"""
    expires = _deadline.get()
    if expires is None:
        return default
    left = expires - time.monotonic()
    if left <= 0:
        raise _exceeded()
    return min(default, left)


def consume_attempt() -> None:
    """Count one upstream attempt, failing once the request's global cap is reached"""
    if _deadline.get() is None:
        return
    check()
    limit = config.REQUEST_MAX_UPSTREAM_ATTEMPTS
    used = _attempts.get()
    if limit > 0 and used >= limit:
        raise HTTPException(
            status_code=503,
            detail="Too many upstream attempts",
            headers={"Retry-After": "5"},
        )
    _attempts.set(used + 1)


def attempts_used() -> int:
    return _attempts.get()


async def sleep(seconds: float) -> None:
    """Back off without sleeping past the request deadline"""
    if _deadline.get() is None:
        await asyncio.sleep(seconds)
        return
    check()
    left = remaining()
    if left is not None and seconds >= left:
        raise _exceeded()
    await asyncio.sleep(seconds)
    check()
