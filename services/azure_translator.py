"""
Azure Translator service for the Terngi Translation API
"""

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException

import config
import metrics
from services.cache import TTLCache

logger = logging.getLogger(__name__)

# Cache of (from_language, to_language, content) -> translated text
translation_cache = TTLCache(max_items=config.CACHE_MAX_ITEMS, ttl=config.CACHE_TTL_SECONDS)

# Azure responses worth retrying: throttling and transient server errors
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Return the Retry-After header (delta-seconds or HTTP-date) in seconds, if valid"""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _retry_delay(attempt: int, response: Optional[httpx.Response]) -> Optional[float]:
    """
    Seconds to wait before retry number `attempt` (0-based), or None to stop

    Uses the server's Retry-After when present, otherwise exponential backoff
    with full jitter. A Retry-After longer than UPSTREAM_RETRY_MAX_DELAY means
    retrying sooner would only be throttled again, so we give up instead.
    """
    if response is not None:
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        if retry_after is not None:
            return retry_after if retry_after <= config.UPSTREAM_RETRY_MAX_DELAY else None
    ceiling = min(config.UPSTREAM_RETRY_MAX_DELAY, config.UPSTREAM_RETRY_BASE_DELAY * 2**attempt)
    return random.uniform(0, ceiling)  # noqa: S311 - jitter, not cryptography


@metrics.timed_upstream("azure")
async def _call_azure(path: str, params: Dict[str, str], texts: List[str]) -> Any:
    """
    Send a request to Azure Translator and return the parsed JSON body

    Args:
        path: API path, e.g. "/translate" or "/detect"
        params: Query parameters (api-version is added automatically)
        texts: Texts to send in the request body

    Returns:
        Parsed JSON response
    """
    if not config.AZURE_TRANSLATOR_KEY:
        raise HTTPException(status_code=503, detail="Translation service is not configured")

    url = config.AZURE_TRANSLATOR_ENDPOINT.rstrip("/") + path

    headers = {
        "Ocp-Apim-Subscription-Key": config.AZURE_TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": config.AZURE_TRANSLATOR_LOCATION,
        "Content-type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }

    body = [{"text": text} for text in texts]

    # Make the request to Azure Translator without blocking the event loop,
    # retrying throttling, transient 5xx and connection errors
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT) as client:
        attempt = 0
        while True:
            response: Optional[httpx.Response] = None
            try:
                response = await client.post(
                    url, params={"api-version": "3.0", **params}, headers=headers, json=body
                )
            except httpx.HTTPError as e:
                retryable = isinstance(e, httpx.TransportError)
                delay = _retry_delay(attempt, None) if retryable else None
                if delay is None or attempt >= config.UPSTREAM_MAX_RETRIES:
                    logger.exception("Error connecting to Azure Translator")
                    raise HTTPException(
                        status_code=502, detail="Error connecting to translation service"
                    ) from e
                reason = type(e).__name__
            else:
                if response.status_code not in RETRY_STATUS_CODES:
                    break
                delay = _retry_delay(attempt, response)
                if delay is None or attempt >= config.UPSTREAM_MAX_RETRIES:
                    break
                reason = str(response.status_code)

            attempt += 1
            logger.warning(
                "Azure Translator %s, retrying in %.2fs (retry %d/%d)",
                reason,
                delay,
                attempt,
                config.UPSTREAM_MAX_RETRIES,
            )
            await asyncio.sleep(delay)

    # Upstream errors are logged but not leaked to the client
    if response.status_code != 200:
        logger.error("Azure Translator returned %s: %s", response.status_code, response.text)
        raise HTTPException(status_code=502, detail="Translation service error")

    try:
        return response.json()
    except ValueError as e:
        raise HTTPException(
            status_code=502, detail="Invalid response from translation service"
        ) from e


async def translate_batch(texts: List[str], from_language: str, to_language: str) -> List[str]:
    """
    Translate several texts in a single Azure request

    Args:
        texts: Texts to translate
        from_language: Source language code
        to_language: Target language code

    Returns:
        Translated texts, in the same order as the input
    """
    # If source and target languages are the same, no need to translate
    if from_language == to_language:
        return list(texts)

    results: List[Optional[str]] = [
        translation_cache.get((from_language, to_language, text)) for text in texts
    ]
    missing = [i for i, result in enumerate(results) if result is None]
    metrics.CACHE_LOOKUPS.labels("hit").inc(len(texts) - len(missing))
    metrics.CACHE_LOOKUPS.labels("miss").inc(len(missing))

    if missing:
        data = await _call_azure(
            "/translate",
            {"from": from_language, "to": to_language},
            [texts[i] for i in missing],
        )
        try:
            translated = [item["translations"][0]["text"] for item in data]
        except (LookupError, TypeError) as e:
            raise HTTPException(status_code=502, detail="No translation result received") from e
        if len(translated) != len(missing):
            raise HTTPException(status_code=502, detail="No translation result received")

        for i, text in zip(missing, translated, strict=True):
            results[i] = text
            translation_cache.set((from_language, to_language, texts[i]), text)

    return [result or "" for result in results]


async def detect_language(content: str) -> Tuple[str, float]:
    """
    Detect the language of a piece of text

    Args:
        content: Text to inspect

    Returns:
        Tuple of (language code, confidence score between 0 and 1)
    """
    data = await _call_azure("/detect", {}, [content])
    try:
        return data[0]["language"], float(data[0].get("score", 0.0))
    except (LookupError, TypeError, ValueError) as e:
        raise HTTPException(status_code=502, detail="No detection result received") from e
