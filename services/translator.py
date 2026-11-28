"""
Translation and language detection over an ordered chain of providers, with caching

Providers come from TRANSLATION_PROVIDERS / DETECTION_PROVIDERS: "azure" or any LLM
provider name. Unconfigured providers are skipped; if one fails the next is tried.

With PII_MASKING, personal data is replaced with placeholders before any provider sees the
text and restored in the result; a provider that drops a placeholder counts as failed (#142).
"""

import hashlib
import logging
from contextvars import ContextVar
from typing import Awaitable, Callable, List, Optional, Sequence, Tuple, TypeVar

from fastapi import HTTPException

import config
import metrics
from services import assistant, azure_translator, deadline, llm, pii, quality
from services.glossary import Glossary, cache_signature, entries_for
from services.store import StoreError, make_store
from services.text import normalize_text

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Cache of (from_language, to_language, content, glossary) -> translated text
translation_cache = make_store("translation", config.CACHE_MAX_ITEMS, config.CACHE_TTL_SECONDS)

# Which callers share one cache entry: bound per request by the middleware when
# config.CACHE_SCOPE is "key" - the caller's key fingerprint, or "public" for keyless
# requests. None means the global cache.
_cache_scope: ContextVar[Optional[str]] = ContextVar("translation_cache_scope", default=None)


def set_cache_scope(scope: Optional[str]):
    """Bind the cache scope for the current request; returns the token to reset with"""
    return _cache_scope.set(scope)


def reset_cache_scope(token) -> None:
    _cache_scope.reset(token)


def _cache_key(
    from_language: str, to_language: str, text: str, glossary: Optional[Glossary] = None
) -> str:
    """Fixed-length cache key, so long texts don't make huge Redis keys"""
    normalized = normalize_text(text)
    payload = f"{from_language}\x00{to_language}\x00{normalized}"
    entries = entries_for(glossary, to_language)
    if entries:
        payload += "\x00" + cache_signature(entries)
    scope = _cache_scope.get()
    if scope is not None:
        # Entries are only shared within one scope, so one caller can't tell (from cache
        # timing) whether another caller recently translated this text
        payload += f"\x00{scope}"
    return hashlib.sha256(payload.encode()).hexdigest()


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
        deadline.check()
        if not _is_configured(name, languages):
            continue
        try:
            result = await (azure_call() if name == "azure" else llm_call(name))
            deadline.check()
            return result
        except HTTPException as e:
            if e.status_code < 500:
                raise
            logger.warning("Provider %s failed (%s); trying the next provider", name, e.status_code)
            last_error = e

    if last_error is None:
        raise HTTPException(status_code=503, detail="Translation service is not configured")
    raise last_error


# Whether the current request's last translate_batch returned an unverified result (#144)
_unverified: ContextVar[bool] = ContextVar("translation_unverified", default=False)


def last_unverified() -> bool:
    """True when the last translation in this request failed every provider's output checks"""
    return _unverified.get()


def _masked(
    call: Callable[[List[str]], Awaitable[List[str]]], texts: List[str]
) -> Callable[[], Awaitable[List[str]]]:
    """
    Wrap a provider call so it only sees masked texts, and restore its results

    A result missing one of its placeholders can't be restored faithfully, so the provider
    is treated as failed (502) and the chain moves on to the next one.
    """
    masked = [pii.mask(text) for text in texts]

    async def run() -> List[str]:
        results = await call([text for text, _ in masked])
        restored: List[str] = []
        for result, (_, replacements) in zip(results, masked, strict=True):
            if pii.missing(result, replacements):
                metrics.PII_PLACEHOLDERS_LOST.inc()
                raise HTTPException(status_code=502, detail="Provider dropped masked values")
            restored.append(pii.unmask(result, replacements))
        return restored

    return run


def _unmasked(
    call: Callable[[List[str]], Awaitable[List[str]]], texts: List[str]
) -> Callable[[], Awaitable[List[str]]]:
    """The provider call as-is (PII_MASKING off)"""
    return lambda: call(texts)


async def translate_text(
    content: str,
    from_language: str,
    to_language: str,
    glossary: Optional[Glossary] = None,
) -> str:
    """
    Translate a single text

    Args:
        content: Text to translate
        from_language: Source language code
        to_language: Target language code
        glossary: Optional terms to protect or translate consistently

    Returns:
        Translated text
    """
    return (await translate_batch([content], from_language, to_language, glossary))[0]


async def translate_batch(
    texts: List[str],
    from_language: str,
    to_language: str,
    glossary: Optional[Glossary] = None,
) -> List[str]:
    """
    Translate several texts, reusing cached results

    Args:
        texts: Texts to translate
        from_language: Source language code
        to_language: Target language code
        glossary: Optional terms to protect or translate consistently

    Returns:
        Translated texts, in the same order as the input
    """
    # Normalise first so composed and decomposed spellings share one cache entry and one
    # provider request.
    texts = [normalize_text(text) for text in texts]

    # If source and target languages are the same, no need to translate
    if from_language == to_language:
        return texts

    deadline.check()
    keys = [_cache_key(from_language, to_language, text, glossary) for text in texts]
    results: List[Optional[str]] = [await _cache_get(key) for key in keys]
    missing = [i for i, result in enumerate(results) if result is None]
    metrics.CACHE_LOOKUPS.labels("hit").inc(len(texts) - len(missing))
    metrics.CACHE_LOOKUPS.labels("miss").inc(len(missing))

    if missing:
        pending = [texts[i] for i in missing]

        def azure_call(items: List[str]) -> Awaitable[List[str]]:
            return azure_translator.translate_batch(items, from_language, to_language, glossary)

        def llm_call(name: str) -> Callable[[List[str]], Awaitable[List[str]]]:
            return lambda items: assistant.translate_batch(
                items, from_language, to_language, name, glossary
            )

        wrap = _masked if config.PII_MASKING else _unmasked
        unverified = False
        token = quality.collect()
        try:
            translated = await _run_chain(
                config.TRANSLATION_PROVIDERS,
                wrap(azure_call, pending),
                lambda name: wrap(llm_call(name), pending)(),
                languages=(from_language, to_language),
            )
        except HTTPException as e:
            # Every provider failed; if some only failed the output checks, the best of those
            # beats an error, as long as the caller is told it is unverified
            candidate = quality.best_candidate()
            if e.status_code < 500 or candidate is None:
                raise
            logger.warning("No translation passed the output checks; returning the best one")
            metrics.TRANSLATIONS_UNVERIFIED.inc()
            translated, unverified = candidate, True
            if config.PII_MASKING:
                # Candidates are offered before unmasking; mask again to restore the values
                masked = [pii.mask(text)[1] for text in pending]
                translated = [pii.unmask(t, r) for t, r in zip(translated, masked, strict=True)]
        finally:
            quality.stop(token)
        _unverified.set(unverified)
        for i, text in zip(missing, translated, strict=True):
            normalized = normalize_text(text)
            results[i] = normalized
            if not unverified:  # never cache a result that failed the checks
                await _cache_set(keys[i], normalized)
    else:
        _unverified.set(False)

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
    if config.PII_MASKING:
        # Placeholders don't change the language, and nothing needs restoring
        content, _ = pii.mask(content)
    language, score = await _run_chain(
        config.DETECTION_PROVIDERS,
        lambda: azure_translator.detect_language(content),
        lambda name: assistant.detect_language(content, name),
    )
    if not isinstance(language, str) or not language.strip():
        raise HTTPException(status_code=502, detail="Invalid language detection result")
    return canonical_language(language), score
