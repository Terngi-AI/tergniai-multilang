"""
Prometheus metrics for the Terngi Translation API

Metrics live in the default prometheus_client registry, which is per process.
That matches the single-process uvicorn CMD in the Dockerfile.
"""

import functools
import time
from contextlib import contextmanager
from typing import Awaitable, Callable, Iterator, List, Optional, ParamSpec, Pattern, Tuple, TypeVar

from fastapi import Request
from prometheus_client import Counter, Histogram
from starlette.routing import compile_path

# Requests by route template, so path parameters can't explode label cardinality
REQUESTS = Counter(
    "terngi_http_requests_total",
    "HTTP requests handled",
    ["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "terngi_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)

# One observation per logical upstream call (retries happen inside it)
UPSTREAM_REQUESTS = Counter(
    "terngi_upstream_requests_total",
    "Calls to upstream services",
    ["service", "outcome"],
)
UPSTREAM_LATENCY = Histogram(
    "terngi_upstream_request_duration_seconds",
    "Upstream call latency, including retries",
    ["service"],
)

CACHE_LOOKUPS = Counter(
    "terngi_translation_cache_lookups_total",
    "Translation cache lookups",
    ["result"],
)
RATE_LIMITED = Counter(
    "terngi_rate_limited_requests_total",
    "Requests rejected with 429 by the rate limiter",
)
AUTH_FAILURES = Counter(
    "terngi_auth_failures_total",
    "Failed API-key authentications",
    ["outcome"],
)
MODERATION_FLAGGED = Counter(
    "terngi_moderation_flagged_total",
    "User messages or tool results flagged by prompt-guard moderation",
    ["kind"],
)

# Per-API-key usage (issue #47). Labels are short SHA-256 hashes, never the key itself.
API_KEY_REQUESTS = Counter(
    "terngi_api_key_requests_total",
    "Requests handled, labelled by a hash of the API key",
    ["key"],
)
API_KEY_UPSTREAM_CALLS = Counter(
    "terngi_api_key_upstream_requests_total",
    "Upstream calls, labelled by a hash of the API key",
    ["key"],
)
API_KEY_TOKENS = Counter(
    "terngi_api_key_tokens_total",
    "Provider-reported tokens, labelled by a hash of the API key",
    ["key", "kind"],
)
API_QUOTA_EXCEEDED = Counter(
    "terngi_api_key_quota_exceeded_total",
    "Requests rejected because the API key's daily quota was exhausted",
    ["key"],
)

P = ParamSpec("P")
T = TypeVar("T")

KNOWN_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


_route_patterns: Optional[List[Tuple[Pattern[str], str]]] = None


def route_label(request: Request) -> str:
    """
    Return the matched route template (e.g. "/v1/translate"), or "unmatched"

    Requests rejected by middleware (401, 429) never reach the router, so their
    path is matched against the templates in the app's OpenAPI schema instead.
    """
    path = getattr(request.scope.get("route"), "path", None)
    if path:
        return path

    global _route_patterns
    if _route_patterns is None:
        templates = request.app.openapi().get("paths", {})
        _route_patterns = [(compile_path(t)[0], t) for t in templates]
    for pattern, template in _route_patterns:
        if pattern.match(request.url.path):
            return template
    return "unmatched"


def method_label(request: Request) -> str:
    """Bucket non-standard HTTP methods so clients can't create new label values"""
    return request.method if request.method in KNOWN_METHODS else "OTHER"


@contextmanager
def track_upstream(service: str) -> Iterator[None]:
    """Count and time an upstream call; an exception marks it as an error"""
    start = time.perf_counter()
    outcome = "error"
    try:
        yield
        outcome = "success"
    finally:
        UPSTREAM_LATENCY.labels(service).observe(time.perf_counter() - start)
        UPSTREAM_REQUESTS.labels(service, outcome).inc()


def timed_upstream(
    service: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator form of track_upstream for async functions"""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            with track_upstream(service):
                return await func(*args, **kwargs)

        return wrapper

    return decorator
