"""
HTTP middleware: request IDs, client authentication and rate limiting
"""

import hmac
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Awaitable, Callable, Deque, Dict, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse

import config
import metrics

logger = logging.getLogger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]

# Paths that never require an API key or count towards the rate limit
PUBLIC_PATHS = {
    "/",
    "/health",
    "/health/ready",
    "/metrics",
    "/v1/languages",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def error_response(status_code: int, message: str, headers: Optional[dict] = None) -> JSONResponse:
    """Build an error in the same envelope as the HTTPException handler"""
    return JSONResponse(
        status_code=status_code,
        content={"error": True, "message": message, "status_code": status_code},
        headers=headers,
    )


class RateLimiter:
    """Sliding-window rate limiter kept in memory (per process)"""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def hit(self, client_id: str) -> "tuple[bool, int, float]":
        """
        Record a request for `client_id`

        Returns:
            (allowed, remaining requests, seconds until a slot frees up)
        """
        now = time.monotonic()
        hits = self._hits[client_id]
        while hits and hits[0] <= now - self.window:
            hits.popleft()

        if len(hits) >= self.limit:
            return False, 0, hits[0] + self.window - now

        hits.append(now)
        return True, self.limit - len(hits), 0.0

    def reset(self) -> None:
        self._hits.clear()


rate_limiter = RateLimiter(limit=config.RATE_LIMIT_PER_MINUTE)


def _client_id(request: Request) -> str:
    """Identify the caller by API key if present, otherwise by IP address"""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return f"key:{api_key}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def _valid_api_key(candidate: Optional[str]) -> bool:
    """Compare against configured keys in constant time"""
    if not candidate:
        return False
    return any(hmac.compare_digest(candidate, key) for key in config.API_KEYS)


async def request_context(request: Request, call_next: CallNext) -> Response:
    """Attach a request ID and timing header to every response"""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    start = time.perf_counter()

    response = await call_next(request)

    elapsed = time.perf_counter() - start
    elapsed_ms = elapsed * 1000
    method, route = metrics.method_label(request), metrics.route_label(request)
    metrics.REQUESTS.labels(method, route, str(response.status_code)).inc()
    metrics.REQUEST_LATENCY.labels(method, route).observe(elapsed)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.info(
        "%s %s -> %s (%.1f ms) [%s]",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        request_id,
    )
    return response


async def authenticate(request: Request, call_next: CallNext) -> Response:
    """Require a valid X-API-Key header when API_KEYS is configured"""
    if config.API_KEYS and request.url.path not in PUBLIC_PATHS and request.method != "OPTIONS":
        if not _valid_api_key(request.headers.get("x-api-key")):
            return error_response(401, "Missing or invalid API key")
    return await call_next(request)


async def rate_limit(request: Request, call_next: CallNext) -> Response:
    """Limit each client to RATE_LIMIT_PER_MINUTE requests"""
    if rate_limiter.limit <= 0 or request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
        return await call_next(request)

    allowed, remaining, retry_after = rate_limiter.hit(_client_id(request))
    headers = {
        "X-RateLimit-Limit": str(rate_limiter.limit),
        "X-RateLimit-Remaining": str(remaining),
    }
    if not allowed:
        headers["Retry-After"] = str(max(1, int(retry_after + 0.999)))
        metrics.RATE_LIMITED.inc()
        return error_response(429, "Rate limit exceeded, please slow down", headers)

    response = await call_next(request)
    response.headers.update(headers)
    return response
