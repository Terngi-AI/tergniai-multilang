"""
Optional prompt-injection moderation using Llama Prompt Guard (issue #38)

When MODERATION_PROVIDERS is set, user messages (and tool text that would be echoed back
into the agent context) are classified before they reach the chat model. Flagged content
is answered with a polite refusal in the user's language, logged without the text itself,
and counted in /metrics. Classifier failures respect MODERATION_FAIL_MODE: "open" lets
the request through, "closed" refuses it with 503. When moderation is disabled there is
no overhead at all.
"""

import logging

from fastapi import HTTPException

import config
from services import llm, translator

logger = logging.getLogger(__name__)

# Prompt Guard 2 answers with "BENIGN" or "INJECTION"; anything containing the marker
# is treated as an injection.
_INJECTION_MARKER = "INJECTION"

REFUSAL_EN = "I'm sorry, but I can't help with this request. Please rephrase your question."


class ModerationError(Exception):
    """The moderation classifier could not be reached"""


def enabled() -> bool:
    return bool(config.MODERATION_PROVIDERS)


def _looks_injected(output: str) -> bool:
    return _INJECTION_MARKER in output.upper()


async def classify(text: str) -> bool:
    """
    Classify `text` with Prompt Guard; True means a prompt injection was detected

    Raises ModerationError when the classifier cannot be reached.
    """
    try:
        verdict = await llm.complete_message(
            config.MODERATION_PROVIDERS,
            [{"role": "user", "content": text}],
            parse=lambda message: message.get("content") or "",
            temperature=0.0,
            max_tokens=32,
            model=config.PROMPT_GUARD_MODEL,
        )
    except HTTPException as e:
        raise ModerationError(str(e.detail)) from e
    return _looks_injected(verdict)


async def refusal(reply_language: str) -> str:
    """A polite refusal in `reply_language`, falling back to English"""
    if reply_language == "en":
        return REFUSAL_EN
    try:
        return await translator.translate_text(REFUSAL_EN, "en", reply_language)
    except HTTPException:
        return REFUSAL_EN


def fail_closed() -> bool:
    """Whether a classifier outage should reject the request"""
    return config.MODERATION_FAIL_MODE == "closed"
