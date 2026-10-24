"""
Azure Translator service for the Terngi Translation API
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException

import config
import metrics
from services import deadline
from services.keypool import key_pool, mask
from services.retry import RETRY_STATUS_CODES
from services.retry import parse_retry_after as _parse_retry_after
from services.retry import retry_delay as _retry_delay

logger = logging.getLogger(__name__)

# Supported languages that Azure Translator does not offer; requests involving them skip Azure
UNSUPPORTED_LANGUAGES = {"pcm", "nr", "om", "lg", "ny", "rn", "wo", "ff", "ee", "tw"}


def supports(*languages: str) -> bool:
    """Whether Azure Translator can translate between these languages"""
    return not UNSUPPORTED_LANGUAGES.intersection(languages)


def _headers(key: str) -> Dict[str, str]:
    return {
        "Ocp-Apim-Subscription-Key": key,
        "Ocp-Apim-Subscription-Region": config.AZURE_TRANSLATOR_LOCATION,
        "Content-type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }


@metrics.timed_upstream("azure")
async def _call_azure(path: str, params: Dict[str, str], texts: List[str]) -> Any:
    """
    Send a request to Azure Translator and return the parsed JSON body

    Keys are tried in rotation: a rejected key (401/403) is skipped for a while and a
    rate-limited key (429) is swapped for another one when available. Throttling,
    transient 5xx and connection errors are retried with exponential backoff.

    Args:
        path: API path, e.g. "/translate" or "/detect"
        params: Query parameters (api-version is added automatically)
        texts: Texts to send in the request body

    Returns:
        Parsed JSON response
    """
    if not config.AZURE_TRANSLATOR_KEYS:
        raise HTTPException(status_code=503, detail="Translation service is not configured")

    keys = key_pool.order("azure", config.AZURE_TRANSLATOR_KEYS)
    if not keys:
        logger.warning("All Azure Translator keys are cooling down")
        raise HTTPException(status_code=502, detail="Translation service error")

    url = config.AZURE_TRANSLATOR_ENDPOINT.rstrip("/") + path
    body = [{"text": text} for text in texts]

    # Make the request to Azure Translator without blocking the event loop
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT) as client:
        attempt = 0
        while True:
            deadline.consume_attempt()
            key = keys[0]
            response: Optional[httpx.Response] = None
            try:
                response = await client.post(
                    url,
                    params={"api-version": "3.0", **params},
                    headers=_headers(key),
                    json=body,
                    timeout=deadline.timeout(config.REQUEST_TIMEOUT),
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
                status = response.status_code
                if status in (401, 403):
                    logger.warning("Azure key %s was rejected; skipping it for a while", mask(key))
                    key_pool.cool_down(key, config.INVALID_KEY_COOLDOWN_SECONDS)
                    keys.pop(0)
                    if keys:
                        continue
                    break
                if status == 429 and len(keys) > 1:
                    logger.warning("Azure key %s is rate-limited; trying the next key", mask(key))
                    key_pool.cool_down(key, _cooldown(response))
                    keys.pop(0)
                    continue
                if status not in RETRY_STATUS_CODES:
                    break
                delay = _retry_delay(attempt, response)
                if delay is None or attempt >= config.UPSTREAM_MAX_RETRIES:
                    if status == 429:
                        key_pool.cool_down(key, _cooldown(response))
                    break
                reason = str(status)

            attempt += 1
            logger.warning(
                "Azure Translator %s, retrying in %.2fs (retry %d/%d)",
                reason,
                delay,
                attempt,
                config.UPSTREAM_MAX_RETRIES,
            )
            await deadline.sleep(delay)

    # Upstream errors are logged but not leaked to the client
    if response is None or response.status_code != 200:
        if response is not None:
            logger.error("Azure Translator returned %s: %s", response.status_code, response.text)
        raise HTTPException(status_code=502, detail="Translation service error")

    try:
        return response.json()
    except ValueError as e:
        raise HTTPException(
            status_code=502, detail="Invalid response from translation service"
        ) from e


def _cooldown(response: httpx.Response) -> float:
    """How long to rest a rate-limited key: its Retry-After, or the default"""
    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
    return config.KEY_COOLDOWN_SECONDS if retry_after is None else retry_after


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
    data = await _call_azure("/translate", {"from": from_language, "to": to_language}, texts)
    try:
        translated = [item["translations"][0]["text"] for item in data]
    except (LookupError, TypeError) as e:
        raise HTTPException(status_code=502, detail="No translation result received") from e
    if len(translated) != len(texts):
        raise HTTPException(status_code=502, detail="No translation result received")
    return translated


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
        language = data[0]["language"]
        score = float(data[0].get("score", 0.0))
    except (LookupError, TypeError, ValueError) as e:
        raise HTTPException(status_code=502, detail="No detection result received") from e
    if not isinstance(language, str) or not language.strip():
        raise HTTPException(status_code=502, detail="No detection result received")
    return language, score
