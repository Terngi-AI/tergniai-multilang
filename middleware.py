"""
HTTP middleware: request IDs, client authentication and rate limiting
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse

import config
import metrics
from services.store import RedisRateLimiter, using_redis

logger = logging.getLogger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]

# Paths that never require an API key or count towards the rate limit
PUBLIC_PATHS = {
    "/chat",
    # Meta calls it; every request is verified by its signature instead of an API key
    "/v1/whatsapp/webhook",
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
        self._calls = 0

    async def hit(self, client_id: str) -> "tuple[bool, int, float]":
        """
        Record a request for `client_id`

        Returns:
            (allowed, remaining requests, seconds until a slot frees up)
        """
        now = time.monotonic()
        self._calls += 1
        if self._calls % 1000 == 0:
            self._sweep(now)
        hits = self._hits[client_id]
        while hits and hits[0] <= now - self.window:
            hits.popleft()

        if len(hits) >= self.limit:
            return False, 0, hits[0] + self.window - now

        hits.append(now)
        return True, self.limit - len(hits), 0.0

    def _sweep(self, now: float) -> None:
        """Forget clients with no requests in the current window, so memory stays bounded"""
        stale = [
            cid for cid, hits in self._hits.items() if not hits or hits[-1] <= now - self.window
        ]
        for cid in stale:
            del self._hits[cid]

    def reset(self) -> None:
        self._hits.clear()
        self._calls = 0


rate_limiter: Any = (
    RedisRateLimiter(limit=config.RATE_LIMIT_PER_MINUTE)
    if using_redis()
    else RateLimiter(limit=config.RATE_LIMIT_PER_MINUTE)
)


def _fingerprint(api_key: str) -> str:
    """Hash keys so raw API keys are never used as dictionary keys or stored in memory"""
    return hashlib.sha256(api_key.encode()).hexdigest()[:32]


def _ip(request: Request) -> str:
    return f"ip:{request.client.host if request.client else 'unknown'}"


def client_id(request: Request) -> str:
    """
    Identify the caller for ownership (e.g. chat conversations): the X-API-Key header if
    sent, otherwise the IP address. Sending a key can only narrow access, never widen it.
    """
    api_key = request.headers.get("x-api-key")
    if api_key:
        # Internal identifier, never sent in a response (Semgrep's Flask XSS rule misfires)
        return "key:" + _fingerprint(api_key)  # nosemgrep
    return _ip(request)


def rate_limit_id(request: Request) -> str:
    """
    Identify the caller for rate limiting. Only a *valid* API key counts; otherwise the IP
    address is used, so clients can't dodge the limit by sending made-up keys.
    """
    api_key = request.headers.get("x-api-key")
    if config.API_KEYS and _valid_api_key(api_key):
        # Internal identifier, never sent in a response (Semgrep's Flask XSS rule misfires)
        return "key:" + _fingerprint(api_key or "")  # nosemgrep
    return _ip(request)


def _valid_api_key(candidate: Optional[str]) -> bool:
    """Compare against configured keys in constant time"""
    if not candidate:
        return False
    return any(hmac.compare_digest(candidate, key) for key in config.API_KEYS)


def _record_request(request: Request, status: int, elapsed: float) -> None:
    method, route = metrics.method_label(request), metrics.route_label(request)
    metrics.REQUESTS.labels(method, route, str(status)).inc()
    metrics.REQUEST_LATENCY.labels(method, route).observe(elapsed)


async def request_context(request: Request, call_next: CallNext) -> Response:
    """Attach a request ID and timing header to every response"""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        # Unhandled errors become a 500 further out; count them before re-raising
        _record_request(request, 500, time.perf_counter() - start)
        raise

    elapsed = time.perf_counter() - start
    elapsed_ms = elapsed * 1000
    _record_request(request, response.status_code, elapsed)
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

    allowed, remaining, retry_after = await rate_limiter.hit(rate_limit_id(request))
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


# --- Security headers ---------------------------------------------------------------------

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# The API only returns JSON, so nothing may load from it
API_CSP = "default-src 'none'; frame-ancestors 'none'"
# The chat page is self-contained: inline script/style, calls to this origin only
CHAT_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
# FastAPI's /docs and /redoc load their UI from a CDN, so they keep the default (no CSP)
NO_CSP_PATHS = {"/docs", "/redoc", "/docs/oauth2-redirect"}


async def security_headers(request: Request, call_next: CallNext) -> Response:
    """Add hardening headers to every response"""
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)

    path = request.url.path
    if path == "/chat":
        response.headers.setdefault("Content-Security-Policy", CHAT_CSP)
    elif path not in NO_CSP_PATHS:
        response.headers.setdefault("Content-Security-Policy", API_CSP)

    # HSTS only means something over HTTPS (directly or behind a TLS-terminating proxy)
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


# --- Request size limit -------------------------------------------------------------------


class BodySizeLimitMiddleware:
    """
    Reject request bodies larger than `max_bytes` with 413, checking both the declared
    Content-Length and the bytes actually received (so chunked uploads can't evade it)
    """

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return

        declared = dict(scope.get("headers") or []).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        rejected = False
        response_started = False

        async def limited_receive() -> Any:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Answer now and tell the app the client went away. Frameworks turn
                    # exceptions raised while reading the body into a 400, so don't raise.
                    rejected = True
                    if not response_started:
                        await self._reject(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Any) -> None:
            nonlocal response_started
            if rejected:
                return  # the 413 has already been sent
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)

    async def _reject(self, send: Any) -> None:
        body = json.dumps(
            {"error": True, "message": "Request body too large", "status_code": 413}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
