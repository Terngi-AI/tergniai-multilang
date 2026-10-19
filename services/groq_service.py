"""
Groq language model service for the Terngi Translation API
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from groq import AsyncGroq

import config
import metrics

logger = logging.getLogger(__name__)

_groq_client: Optional[AsyncGroq] = None


def get_client() -> AsyncGroq:
    """Create the Groq client lazily so the app can start without a key"""
    global _groq_client
    if _groq_client is None:
        if not config.GROQ_API_KEY:
            raise HTTPException(status_code=503, detail="Language model service is not configured")
        # The SDK retries 408/409/429/5xx and connection errors itself, with
        # exponential backoff, jitter and Retry-After support.
        _groq_client = AsyncGroq(
            api_key=config.GROQ_API_KEY,
            timeout=config.REQUEST_TIMEOUT,
            max_retries=config.UPSTREAM_MAX_RETRIES,
        )
    return _groq_client


async def get_response(content: str, memory_context: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Get response from Groq LLM (always in English)

    Args:
        content: User message content (in English)
        memory_context: Optional conversation history for context

    Returns:
        LLM response in English
    """
    # Format conversation history
    messages: List[Dict[str, Any]] = []

    # Add system prompt with instructions
    messages.append({"role": "system", "content": config.GROQ_SYSTEM_PROMPT})

    # Add memory context if provided (only user/assistant turns are allowed)
    if memory_context:
        for message in memory_context:
            if message.get("role") in ("user", "assistant") and "content" in message:
                messages.append({"role": message["role"], "content": message["content"]})

    # Add the current user message
    messages.append({"role": "user", "content": content})

    client = get_client()

    # Call Groq API
    try:
        with metrics.track_upstream("groq"):
            completion = await client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.7,
                max_tokens=1024,
            )
    except Exception as e:
        logger.exception("Error calling Groq")
        raise HTTPException(
            status_code=502, detail="Error connecting to language model service"
        ) from e

    # Extract and return the response
    return completion.choices[0].message.content or ""


def _language_name(code: str) -> str:
    """Human-readable language name for prompts"""
    return config.SUPPORTED_LANGUAGES.get(code, code)


async def _complete_json(system: str, user: str) -> Dict[str, Any]:
    """Ask the model for a JSON object and parse it"""
    client = get_client()
    try:
        completion = await client.chat.completions.create(
            model=config.GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.exception("Error calling Groq")
        raise HTTPException(
            status_code=502, detail="Error connecting to language model service"
        ) from e

    try:
        data = json.loads(completion.choices[0].message.content or "")
    except (ValueError, LookupError, AttributeError) as e:
        raise HTTPException(status_code=502, detail="Invalid response from language model") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Invalid response from language model")
    return data


async def translate_batch(texts: List[str], from_language: str, to_language: str) -> List[str]:
    """
    Translate texts with the LLM (used when Azure Translator is unavailable)

    Args:
        texts: Texts to translate
        from_language: Source language code
        to_language: Target language code

    Returns:
        Translated texts, in the same order as the input
    """
    source, target = _language_name(from_language), _language_name(to_language)
    system = (
        f"You are a professional translator from {source} to {target}. "
        f"Translate every string in the JSON array 'texts' into {target}. "
        f"Use correct {target} orthography, including tone marks and diacritics. "
        "Preserve meaning, tone, names, numbers and formatting. Do not add explanations. "
        'Reply only with a JSON object: {"translations": [...]} containing exactly one '
        "translated string per input, in the same order."
    )
    data = await _complete_json(system, json.dumps({"texts": texts}, ensure_ascii=False))

    translations = data.get("translations")
    if (
        not isinstance(translations, list)
        or len(translations) != len(texts)
        or not all(isinstance(t, str) for t in translations)
    ):
        raise HTTPException(status_code=502, detail="No translation result received")
    return translations


async def detect_language(content: str) -> Tuple[str, float]:
    """
    Detect the language of a text with the LLM (used when Azure Translator is unavailable)

    Returns:
        Tuple of (ISO 639-1 language code, confidence score between 0 and 1)
    """
    system = (
        "Identify the language of the user's text. Reply only with a JSON object: "
        '{"language": "<ISO 639-1 code, e.g. en, yo, ha, ig>", "score": <confidence 0-1>}'
    )
    data = await _complete_json(system, content)

    language = data.get("language")
    if not isinstance(language, str) or not language.strip():
        raise HTTPException(status_code=502, detail="No detection result received")
    try:
        score = min(max(float(data.get("score", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        score = 0.0
    return language.strip().lower(), score
