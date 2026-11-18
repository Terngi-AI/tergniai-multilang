from typing import Optional

import httpx

from config import REQUEST_TIMEOUT  # या जहाँ से REQUEST_TIMEOUT इम्पोर्ट होता है

# प्रोसेस-लेवल शेयर्ड क्लाइंट
_client: Optional[httpx.AsyncClient] = None

# कनेक्शन पूल सेटिंग्स
MAX_CONNECTIONS = 100
MAX_KEEPALIVE_CONNECTIONS = 20


async def get_http_client() -> httpx.AsyncClient:

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
    """FastAPI lifespan स्टार्टअप पर क्लाइंट को इनिशियलाइज़ करता है।"""
    await get_http_client()


async def close_http_client() -> None:

    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
