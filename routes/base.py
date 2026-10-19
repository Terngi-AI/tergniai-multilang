"""
Base routes for the Terngi Translation API
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

import config
from config import SUPPORTED_LANGUAGES
from services import llm
from services.translator import translation_available

router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint returning API information"""
    return {
        "message": "Welcome to the Terngi Translation API v1",
        "supported_languages": SUPPORTED_LANGUAGES,
    }


@router.get("/v1/languages")
async def get_supported_languages():
    """Get list of supported languages"""
    return {"languages": SUPPORTED_LANGUAGES}


@router.get("/health")
async def health():
    """Liveness probe used by Docker and load balancers"""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready():
    """Readiness probe: reports whether upstream services are configured"""
    services = {
        "translator": translation_available(),
        "llm": llm.is_configured(config.CHAT_PROVIDERS),
        "agent": llm.is_configured(config.AGENT_PROVIDERS, kind="openai"),
    }
    is_ready = all(services.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={"status": "ready" if is_ready else "not_ready", "services": services},
    )
