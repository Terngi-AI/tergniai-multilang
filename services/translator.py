"""
Translation and language detection over an ordered chain of providers, with caching

Providers come from TRANSLATION_PROVIDERS / DETECTION_PROVIDERS: "azure" or any LLM
provider name. Unconfigured providers are skipped; if one fails the next is tried.
"""

import logging
from typing import Awaitable, Callable, List, Optional, Sequence, Tuple, TypeVar

from fastapi import HTTPException

import config
import metrics
from services import assistant, azure_translator
from services.cache import TTLCache

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Cache of (from_language, to_language, content) -> translated text
translation_cache = TTLCache(max_items=config.CACHE_MAX_ITEMS, ttl=config.CACHE_TTL_SECONDS)


def _is_configured(name: str, languages: Sequence[str] = ()) -> bool:
    if name == "azure":
        return bool(config.AZURE_TRANSLATOR_KEYS) and azure_translator.supports(*languages)
    provider = config.LLM_PROVIDERS.get(name)
    return provider is not None and provider.configured and provider.supports(*languages)


def translation_available() -> bool:
    """Whether any translation provider is configured"""
    return any(_is_configured(name) for name in config.TRANSLATION_PROVIDERS)


async def _run_chain(
    providers: Sequence[str],
    azure_call: Callable[[], Awaitable[T]],
    llm_call: Callable[[str], Awaitable[T]],
    languages: Sequence[str] = (),
) -> T:
    """Try each configured provider that supports `languages`, in order, until one succeeds"""
    last_error: Optional[HTTPException] = None

    for name in providers:
        if not _is_configured(name, languages):
            continue
        try:
            return await (azure_call() if name == "azure" else llm_call(name))
        except HTTPException as e:
            if e.status_code < 500:
                raise
            logger.warning("Provider %s failed (%s); trying the next provider", name, e.status_code)
            last_error = e

    if last_error is None:
        raise HTTPException(status_code=503, detail="Translation service is not configured")
    raise last_error


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
    metrics.CACHE_LOOKUPS.labels("hit").inc(len(texts) - len(missing))
    metrics.CACHE_LOOKUPS.labels("miss").inc(len(missing))

    if missing:
        pending = [texts[i] for i in missing]
        translated = await _run_chain(
            config.TRANSLATION_PROVIDERS,
            lambda: azure_translator.translate_batch(pending, from_language, to_language),
            lambda name: assistant.translate_batch(pending, from_language, to_language, name),
            languages=(from_language, to_language),
        )
        for i, text in zip(missing, translated, strict=True):
            results[i] = text
            translation_cache.set((from_language, to_language, texts[i]), text)

    return [result or "" for result in results]


# Codes that detectors commonly return, mapped to the codes used by this API
LANGUAGE_ALIASES = {
    "zh": "zh-Hans",
    "zh-cn": "zh-Hans",
    "zh-sg": "zh-Hans",
    "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant",
    "sr": "sr-Latn",
    "no": "nb",
    "tl": "fil",
    "iw": "he",
    "in": "id",
    "pt-br": "pt",
    "pt-pt": "pt",
    "nd": "nr",
    "ak": "tw",
}

_CANONICAL = {code.lower(): code for code in config.SUPPORTED_LANGUAGES}


def canonical_language(code: str) -> str:
    """Map a detected code to the API's spelling (case-insensitive, with common aliases)"""
    lowered = code.strip().lower().replace("_", "-")
    lowered = LANGUAGE_ALIASES.get(lowered, lowered).lower()
    return _CANONICAL.get(lowered, code.strip())


async def detect_language(content: str) -> Tuple[str, float]:
    """
    Detect the language of a piece of text

    Returns:
        Tuple of (language code, confidence score between 0 and 1)
    """
    language, score = await _run_chain(
        config.DETECTION_PROVIDERS,
        lambda: azure_translator.detect_language(content),
        lambda name: assistant.detect_language(content, name),
    )
    return canonical_language(language), score
