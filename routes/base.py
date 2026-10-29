"""
Base routes for the Terngi Translation API
"""

from typing import Dict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

import config
import middleware
from config import SUPPORTED_LANGUAGES
from models import UsageResponse, UsageStats
from services import llm, store, usage
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


@router.get("/v1/usage", response_model=UsageResponse)
async def usage_report(http_request: Request):
    """
    Daily usage for the calling API key

    Returns the counters for today (and yesterday, when it has any) plus the configured
    daily quota and how many requests are left. Only a valid API key is counted; without
    API keys configured there is no per-key usage to report.
    """
    from datetime import date, timedelta

    api_key = middleware.authenticated_key(http_request)
    if api_key is None:
        return UsageResponse(usage=[])

    label = usage.key_label(api_key)
    today = usage.today()
    today_usage = await usage.snapshot(label, today)
    days = [today]

    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    yesterday_usage = await usage.snapshot(label, yesterday)
    if yesterday_usage.requests or yesterday_usage.upstream_calls:
        days.insert(0, yesterday)

    stats = []
    for day in days:
        current = today_usage if day == today else yesterday_usage
        stats.append(UsageStats(date=day, total_tokens=current.total_tokens, **current.as_dict()))

    quota = usage.quota_for(api_key)
    remaining = None
    if quota is not None:
        remaining = max(0, quota - today_usage.requests)

    return UsageResponse(
        usage=stats,
        quota=quota,
        remaining=remaining,
        resets_at=usage.reset_at() if quota is not None else None,
    )


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """
    Prometheus scrape endpoint. Requires a valid API key when authentication is
    configured, or the dedicated METRICS_TOKEN bearer token ("Authorization: Bearer ...").
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health/ready")
async def ready(request: Request):
    """
    Readiness probe for translation, chat and the optional agent path.

    Optional dependencies do not fail readiness: the cache fails open and the agent has its
    own endpoint. A degraded status is returned so operators can alert on it without
    draining every replica when Redis has a blip.

    The probe itself is public (load balancers), but the per-service list reveals the
    configuration, so it is only included for authenticated callers.
    """
    services = {
        "translator": translation_available(),
        "llm": llm.is_configured(config.CHAT_PROVIDERS),
        "agent": llm.is_configured(config.AGENT_PROVIDERS, kind="openai"),
        "storage": await store.ping(),
        "auth": bool(config.API_KEYS),
    }
    core_ready = services["translator"] or services["llm"] or services["agent"]
    # auth is reported but never makes readiness degrade
    health = {name: ok for name, ok in services.items() if name != "auth"}
    status = "not_ready" if not core_ready else "ready" if all(health.values()) else "degraded"
    content: Dict[str, object] = {"status": status}
    if middleware.is_authenticated(request):
        content["services"] = services
    return JSONResponse(
        status_code=200 if core_ready else 503,
        content=content,
    )
