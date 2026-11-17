"""
Optional prompt-injection moderation using Llama Prompt Guard (issue #38)

When MODERATION_PROVIDERS is set, user messages (and tool text that would be echoed back
into the agent context) are classified before they reach the chat model. Flagged content
is answered with a polite refusal in the user's language, logged without the text itself,
and counted in /metrics. Classifier failures respect MODERATION_FAIL_MODE: "open" lets
the request through, "closed" refuses it with 503. When moderation is disabled there is
no overhead at all.

The classifier is called with model=PROMPT_GUARD_MODEL, which is never part of the chat
fallback chain: even if the guard model is listed in a provider's MODELS, a chat request
(model=None) will not fall back to it, because a guard verdict is not an answer.

Groq answers Prompt Guard 2 with a probability score ("0.9876"); label-based answers
("INJECTION"/"MALICIOUS") from other deployments are matched as a fallback. Note:
Prompt Guard 2 has a 512-token context, so only the beginning of very long messages is
classified.
"""

import logging
import re
from typing import Optional

from fastapi import HTTPException

import config
from services import llm, translator

logger = logging.getLogger(__name__)

# Groq answers with a bare probability score, e.g. "0.9876" (benign texts score near 0)
_SCORE_RE = re.compile(r"-?\d+(?:\.\d+)?")
# Label-based outputs from Prompt Guard 1/2 deployments that do not return a score
_INJECTION_LABELS = ("INJECTION", "MALICIOUS", "JAILBREAK")
_BENIGN_LABELS = ("BENIGN", "NOT INJECTION", "NOT MALICIOUS")

REFUSAL_EN = "I'm sorry, but I can't help with this request. Please rephrase your question."


class ModerationError(Exception):
    """The moderation classifier could not be reached"""


def enabled() -> bool:
    return bool(config.MODERATION_PROVIDERS)


def _interpret(output: str) -> Optional[bool]:
    """
    Interpret the classifier output: True = injection, False = benign, None = unparseable

    A numeric answer is a probability score, compared against MODERATION_THRESHOLD.
    Otherwise the answer is matched against the labels the model card documents.
    """
    score = _SCORE_RE.search(output.strip())
    if score:
        return float(score.group()) >= config.MODERATION_THRESHOLD
    upper = output.upper()
    # The benign labels are checked first: "NOT INJECTION" and "NOT MALICIOUS" contain
    # the injection words, so matching them second would flag benign answers.
    if any(label in upper for label in _BENIGN_LABELS):
        return False
    if any(label in upper for label in _INJECTION_LABELS):
        return True
    return None


async def classify(text: str) -> bool:
    """
    Classify `text` with Prompt Guard; True means a prompt injection was detected

    The guard model does not need to be listed in the provider's MODELS, and it is never
    used as a chat fallback (see the module docstring). Note that Prompt Guard 2 has a
    512-token context, so very long messages are only partly classified.

    Raises ModerationError when the classifier cannot be reached or answers with
    something that can't be interpreted; the caller then applies MODERATION_FAIL_MODE.
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
    injected = _interpret(verdict)
    if injected is None:
        # No content is logged: the verdict can echo the user's message back. An
        # unparseable answer is a classifier failure, so the caller applies
        # MODERATION_FAIL_MODE (fail-open passes the request, fail-closed returns 503).
        logger.warning("Moderation classifier returned an unparseable answer")
        raise ModerationError("classifier returned an unparseable answer")
    return bool(injected)


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
