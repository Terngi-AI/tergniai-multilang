"""
Translation and language detection with provider selection, fallback and caching
"""

import logging
from typing import Awaitable, Callable, List, Optional, Tuple, TypeVar

from fastapi import HTTPException

import config
from services import azure_translator, groq_service
from services.cache import TTLCache

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Cache of (from_language, to_language, content) -> translated text
translation_cache = TTLCache(max_items=config.CACHE_MAX_ITEMS, ttl=config.CACHE_TTL_SECONDS)


def translation_available() -> bool:
    """Whether any configured provider can translate"""
    if config.TRANSLATION_PROVIDER == "azure":
        return bool(config.AZURE_TRANSLATOR_KEY)
    if config.TRANSLATION_PROVIDER == "groq":
        return bool(config.GROQ_API_KEY)
    return bool(config.AZURE_TRANSLATOR_KEY or config.GROQ_API_KEY)


async def _with_fallback(
    azure_call: Callable[[], Awaitable[T]], groq_call: Callable[[], Awaitable[T]]
) -> T:
    """Run the call on the configured provider, falling back from Azure to Groq in auto mode"""
    provider = config.TRANSLATION_PROVIDER

    if not translation_available():
        raise HTTPException(status_code=503, detail="Translation service is not configured")

    if provider == "groq" or (provider == "auto" and not config.AZURE_TRANSLATOR_KEY):
        return await groq_call()

    try:
        return await azure_call()
    except HTTPException as e:
        if provider == "auto" and config.GROQ_API_KEY and e.status_code >= 500:
            logger.warning("Azure Translator failed (%s); falling back to Groq", e.status_code)
            return await groq_call()
        raise


async def translate_text(content: str, from_language: str, to_language: str) -> str:
    """
    Translate a single text

    Args:
        content: Text to translate
        from_language: Source language code
        to_language: Target language code

    Returns:
        Translated text
    """
    return (await translate_batch([content], from_language, to_language))[0]


async def translate_batch(texts: List[str], from_language: str, to_language: str) -> List[str]:
    """
    Translate several texts, reusing cached results

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

    if missing:
        pending = [texts[i] for i in missing]
        translated = await _with_fallback(
            lambda: azure_translator.translate_batch(pending, from_language, to_language),
            lambda: groq_service.translate_batch(pending, from_language, to_language),
        )
        for i, text in zip(missing, translated, strict=True):
            results[i] = text
            translation_cache.set((from_language, to_language, texts[i]), text)

    return [result or "" for result in results]


async def detect_language(content: str) -> Tuple[str, float]:
    """
    Detect the language of a piece of text

    Returns:
        Tuple of (language code, confidence score between 0 and 1)
    """
    return await _with_fallback(
        lambda: azure_translator.detect_language(content),
        lambda: groq_service.detect_language(content),
    )
