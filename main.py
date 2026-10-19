"""
Main application entry point for Terngi Translation API
"""

import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import middleware
from config import CORS_ORIGINS, MAX_REQUEST_BYTES

# Import routers
from routes import agent, base, chat, conversation, translation

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Initialize FastAPI app
app = FastAPI(
    title="Terngi Translation API",
    description="Translation, conversation and a multilingual AI agent for African languages",
    version="1.0.0",
)

# Middleware runs in reverse order of registration:
# body size limit -> security headers -> request context -> auth -> rate limit
app.middleware("http")(middleware.rate_limit)
app.middleware("http")(middleware.authenticate)
app.middleware("http")(middleware.request_context)
app.middleware("http")(middleware.security_headers)
app.add_middleware(middleware.BodySizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)

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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": True, "message": exc.detail, "status_code": exc.status_code},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return validation errors in the same envelope as other errors"""
    return JSONResponse(
        status_code=422,
        content={
            "error": True,
            "message": "Invalid request",
            "details": jsonable_errors(exc),
            "status_code": 422,
        },
    )


def jsonable_errors(exc: RequestValidationError) -> list:
    """Strip non-serialisable context from pydantic errors"""
    return [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
