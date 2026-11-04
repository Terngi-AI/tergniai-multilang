"""
Main application entry point for Terngi Translation API
"""

import logging
import os
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
import metrics
import middleware
from config import CORS_ORIGINS, MAX_REQUEST_BYTES

# Import routers
from routes import agent, base, chat, conversation, feedback, translation, whatsapp

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def check_authentication() -> None:
    """
    Refuse to run with authentication disabled outside an explicitly allowed setup

    API_KEYS empty means every endpoint is public. That is only acceptable for local
    development, where the operator opts in with ALLOW_UNAUTHENTICATED=true.
    """
    if config.API_KEYS:
        return
    if not config.ALLOW_UNAUTHENTICATED:
        raise SystemExit(
            "API_KEYS is empty and ALLOW_UNAUTHENTICATED is not 'true'. Refusing to "
            "start: every endpoint would be public. Set API_KEYS, or set "
            "ALLOW_UNAUTHENTICATED=true only for local development."
        )
    logger.warning(
        "API_KEYS is empty and ALLOW_UNAUTHENTICATED=true: authentication is disabled. "
        "Never deploy this way."
    )


check_authentication()


def check_hash_secret() -> None:
    """
    Refuse to run without the keying secret for personal identifiers

    WhatsApp phone numbers and IP-based conversation owners are stored as HMAC-SHA256
    under HASH_SECRET. Without it they would be plain unsalted hashes, which can be
    reversed by brute force because phone numbers and IPv4 addresses are small spaces.
    """
    if not config.HASH_SECRET:
        raise SystemExit(
            "HASH_SECRET is empty. Refusing to start: WhatsApp phone numbers and "
            "IP-based conversation owners are keyed with HMAC-SHA256 under this "
            "secret, and a plain unsalted hash of them could be reversed by brute "
            'force. Generate one with: python -c "import secrets; '
            'print(secrets.token_hex(32))" and set it as an environment variable.'
        )


check_hash_secret()


# Endpoint groups shown in /docs, in the order they are listed
OPENAPI_TAGS = [
    {
        "name": "translation",
        "description": "Translate one or many texts, and detect the language of a text",
    },
    {
        "name": "conversation",
        "description": "Multilingual chat (with streaming), the tool-using agent and /v1/converse",
    },
    {
        "name": "whatsapp",
        "description": "Send WhatsApp messages on the connected business number",
    },
    {
        "name": "account",
        "description": "Per-key usage and opt-in translation feedback",
    },
    {
        "name": "health",
        "description": "Public status, readiness and supported-language reference endpoints",
    },
]

# Initialize FastAPI app
app = FastAPI(
    title="Terngi Translation API",
    description="Translation, conversation and a multilingual AI agent for local languages",
    version="1.0.0",
    openapi_tags=OPENAPI_TAGS,
)

# Middleware runs in reverse order of registration:
# body size limit -> security headers -> request context -> auth -> usage limits -> rate limit
app.middleware("http")(middleware.rate_limit)
app.middleware("http")(middleware.usage_limits)
app.middleware("http")(middleware.authenticate)
app.middleware("http")(middleware.request_context)
app.middleware("http")(middleware.security_headers)
app.add_middleware(middleware.BodySizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)
# Outermost: the deadline covers authentication, handlers and streamed responses
app.add_middleware(middleware.DeadlineMiddleware)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

# Include routers
app.include_router(base.router)
app.include_router(translation.router)
app.include_router(conversation.router)
app.include_router(agent.router)
app.include_router(chat.router)
app.include_router(feedback.router)
app.include_router(whatsapp.router)


def _openapi() -> Dict[str, Any]:
    """
    Build the OpenAPI schema with the API key scheme the middleware enforces

    Authentication happens in middleware (see middleware.authenticate), so FastAPI does
    not see it: declare the scheme here so /docs shows an "Authorize" button, and
    require it on every operation (public routes opt out with security=[]).
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=OPENAPI_TAGS,
    )
    schema.setdefault("components", {})["securitySchemes"] = {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }
    schema["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


# Swap in the schema builder so /openapi.json, /docs and the export script all carry
# the API key scheme
app.openapi = _openapi  # type: ignore[method-assign]


_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    502: "upstream_error",
    503: "service_unavailable",
    504: "gateway_timeout",
    507: "insufficient_storage",
}


def _error_code(status_code: int) -> str:
    return _ERROR_CODES.get(status_code, "http_error")


def _error_headers(request: Request) -> Dict[str, str]:
    """Security and correlation headers for errors that bypass the middleware stack"""
    headers = middleware.security_headers_for(request.url.path, request.url.scheme)
    request_id = getattr(request.state, "request_id", "")
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle routing, method and application HTTP errors with one JSON envelope"""
    headers = _error_headers(request)
    if exc.headers:
        headers.update(exc.headers)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "code": _error_code(exc.status_code),
            "status_code": exc.status_code,
        },
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return validation errors in the same envelope as other errors"""
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "message": "Invalid request",
            "code": "validation_error",
            "details": jsonable_errors(exc),
            "status_code": 422,
        },
        headers=_error_headers(request),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Never leak a traceback or a plain-text 500 to the client"""
    logger.error(
        "Unhandled error while processing %s %s",
        request.method,
        metrics.route_label(request),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "code": "internal_error",
            "status_code": 500,
        },
        headers=_error_headers(request),
    )


def jsonable_errors(exc: RequestValidationError) -> list:
    """Strip non-serialisable context from pydantic errors"""
    return [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
