"""
Translation and language detection over an ordered chain of providers, with caching

Providers come from TRANSLATION_PROVIDERS / DETECTION_PROVIDERS: "azure" or any LLM
provider name. Unconfigured providers are skipped; if one fails the next is tried.
"""

import hashlib
import logging
from typing import Awaitable, Callable, List, Optional, Sequence, Tuple, TypeVar

from fastapi import HTTPException

import config
import metrics
from services import assistant, azure_translator, llm
from services.store import StoreError, make_store
from services.text import normalize_text

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Cache of (from_language, to_language, content) -> translated text
translation_cache = make_store("translation", config.CACHE_MAX_ITEMS, config.CACHE_TTL_SECONDS)


def _cache_key(from_language: str, to_language: str, text: str) -> str:
    """Fixed-length cache key, so long texts don't make huge Redis keys"""
    normalized = normalize_text(text)
    return hashlib.sha256(f"{from_language}\x00{to_language}\x00{normalized}".encode()).hexdigest()


async def _cache_get(key: str) -> Optional[str]:
    try:
        return await translation_cache.get(key)
    except StoreError:
        logger.warning("Translation cache unavailable; translating without it")
        return None


async def _cache_set(key: str, value: str) -> None:
    try:
        await translation_cache.set(key, value)
    except StoreError:
        logger.warning("Translation cache unavailable; result not cached")


def _is_configured(name: str, languages: Sequence[str] = ()) -> bool:
    if name == "azure":
        return bool(config.AZURE_TRANSLATOR_KEYS) and azure_translator.supports(*languages)
    provider = config.LLM_PROVIDERS.get(name)
    # Providers resting after being unreachable are skipped quietly
    return llm.is_available(name) and provider is not None and provider.supports(*languages)


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
    # Normalise first so composed and decomposed spellings share one cache entry and one
    # provider request.
    texts = [normalize_text(text) for text in texts]

    # If source and target languages are the same, no need to translate
    if from_language == to_language:
        return texts

    keys = [_cache_key(from_language, to_language, text) for text in texts]
    results: List[Optional[str]] = [await _cache_get(key) for key in keys]
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
            normalized = normalize_text(text)
            results[i] = normalized
            await _cache_set(keys[i], normalized)

    return [normalize_text(result or "") for result in results]


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
    content = normalize_text(content)
    language, score = await _run_chain(
        config.DETECTION_PROVIDERS,
        lambda: azure_translator.detect_language(content),
        lambda name: assistant.detect_language(content, name),
    )
    if not isinstance(language, str) or not language.strip():
        raise HTTPException(status_code=502, detail="Invalid language detection result")
    return canonical_language(language), score
