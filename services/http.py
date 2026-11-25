"""Shared HTTP client lifecycle management."""

from typing import Optional

import httpx

from config import REQUEST_TIMEOUT

_client: Optional[httpx.AsyncClient] = None

MAX_CONNECTIONS = 100
MAX_KEEPALIVE_CONNECTIONS = 20


async def get_http_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient instance, initializing it if needed."""
    global _client
    if _client is None or _client.is_closed:
        limits = httpx.Limits(
            max_connections=MAX_CONNECTIONS,
            max_keepalive_connections=MAX_KEEPALIVE_CONNECTIONS,
        )
        _client = httpx.AsyncClient(
            limits=limits,
            timeout=REQUEST_TIMEOUT,
        )
    return _client


async def init_http_client() -> None:
    """Initialize the shared HTTP client at application startup."""
    await get_http_client()


async def close_http_client() -> None:
    """Close the shared HTTP client during application shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
