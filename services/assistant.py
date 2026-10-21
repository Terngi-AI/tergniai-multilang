"""
Conversation, translation and language detection performed by language models
"""

import json
from typing import Any, Dict, List, Optional, Tuple

import config
from services import llm


def _language_name(code: str) -> str:
    """Human-readable language name for prompts"""
    return config.SUPPORTED_LANGUAGES.get(code, code)


def _non_empty(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("empty output")
    return text


async def get_response(content: str, memory_context: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Get a conversational reply (always in English) from the chat providers

    Args:
        content: User message content (in English)
        memory_context: Optional conversation history for context

    Returns:
        Reply in English
    """
    messages: List[Dict[str, str]] = [{"role": "system", "content": config.SYSTEM_PROMPT}]

    # Add memory context if provided (only user/assistant turns are allowed)
    if memory_context:
        for message in memory_context:
            if message.get("role") in ("user", "assistant") and "content" in message:
                messages.append({"role": message["role"], "content": message["content"]})

    messages.append({"role": "user", "content": content})

    return await llm.complete(
        config.CHAT_PROVIDERS, messages, parse=_non_empty, temperature=0.7, max_tokens=1024
    )


async def translate_batch(
    texts: List[str], from_language: str, to_language: str, provider: str
) -> List[str]:
    """
    Translate texts with one LLM provider

    Args:
        texts: Texts to translate
        from_language: Source language code
        to_language: Target language code
        provider: LLM provider name

    Returns:
        Translated texts, in the same order as the input
    """
    source, target = _language_name(from_language), _language_name(to_language)

    # Small models such as MORENA are more reliable translating one plain-text item at a time
    if config.LLM_PROVIDERS[provider].kind == "morena":
        instruction = (
            f"Translate the following text from {source} to {target}. "
            "Reply with only the translation."
        )
        return [
            await llm.complete(
                [provider],
                [{"role": "user", "content": f"{instruction}\n\n{text}"}],
                parse=_non_empty,
                temperature=0.1,
                max_tokens=512,
            )
            for text in texts
        ]

    # A single text needs no JSON wrapper. Plain text is also more reliable for long texts:
    # strict JSON mode makes some providers reject outputs they can't validate.
    if len(texts) == 1:
        system = (
            f"You are a professional translator from {source} to {target}. "
            f"Translate the user's text into {target}. "
            f"Use correct {target} orthography, including tone marks and diacritics. "
            "Preserve meaning, tone, names, numbers and formatting. "
            "Reply with only the translation: no quotes, notes or explanations."
        )
        return [
            await llm.complete(
                [provider],
                [{"role": "system", "content": system}, {"role": "user", "content": texts[0]}],
                parse=_non_empty,
                temperature=0.2,
            )
        ]

    system = (
        f"You are a professional translator from {source} to {target}. "
        f"Translate every string in the JSON array 'texts' into {target}. "
        f"Use correct {target} orthography, including tone marks and diacritics. "
        "Preserve meaning, tone, names, numbers and formatting. Do not add explanations. "
        'Reply only with a JSON object: {"translations": [...]} containing exactly one '
        "translated string per input, in the same order."
    )

    def parse(text: str) -> List[str]:
        translations = llm.parse_json_object(text).get("translations")
        if (
            not isinstance(translations, list)
            or len(translations) != len(texts)
            or not all(isinstance(t, str) for t in translations)
        ):
            raise ValueError("translations missing or wrong length")
        return translations

    return await llm.complete(
        [provider],
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"texts": texts}, ensure_ascii=False)},
        ],
        parse=parse,
        json_mode=True,
        temperature=0.2,
    )


async def detect_language(content: str, provider: str) -> Tuple[str, float]:
    """
    Detect the language of a text with one LLM provider

    Returns:
        Tuple of (ISO 639-1 language code, confidence score between 0 and 1)
    """
    known = ", ".join(f"{code} = {name}" for code, name in config.SUPPORTED_LANGUAGES.items())
    system = (
        "Identify the language of the user's text. Use one of these codes when it matches "
        f"({known}). Nigerian Pidgin is 'pcm', not English; isiNdebele is 'nr' and isiZulu is 'zu'. "
        "Otherwise use the ISO 639 code. "
        'Reply only with a JSON object: {"language": "<code>", "score": <confidence 0-1>}'
    )

    def parse(text: str) -> Tuple[str, float]:
        data = llm.parse_json_object(text)
        language = data.get("language")
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language missing")
        try:
            score = min(max(float(data.get("score", 0.0)), 0.0), 1.0)
        except (TypeError, ValueError):
            score = 0.0
        return language.strip().lower(), score

    return await llm.complete(
        [provider],
        [{"role": "system", "content": system}, {"role": "user", "content": content}],
        parse=parse,
        json_mode=True,
        temperature=0.0,
    )
