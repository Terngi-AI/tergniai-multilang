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
("INJECTION"/"MALICIOUS") from other deployments are matched as a fallback.

Prompt Guard 2 only reads 512 tokens, so a long text is split into overlapping chunks of
MODERATION_CHUNK_CHARS characters, classified concurrently; any flagged chunk flags the text
(#168). One check classifies at most MODERATION_MAX_CHUNKS chunks, so long input can't
multiply the cost; a text needing more counts as a classifier failure (MODERATION_FAIL_MODE).

Prompt Guard is weaker on low-resource languages, so callers also pass the English
translation of a non-English message when they have one (see `flagged()`).
"""

import asyncio
import logging
import re
from typing import List, Optional, Sequence, Tuple

from fastapi import HTTPException

import config
import metrics
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


def chunks(text: str) -> List[str]:
    """
    Split a text into overlapping windows the classifier can read in full

    The overlap means an instruction cut at a chunk boundary still appears whole in one of
    the two neighbouring chunks, as long as it is shorter than the overlap.
    """
    size = max(config.MODERATION_CHUNK_CHARS, 1)
    if len(text) <= size:
        return [text]
    overlap = min(max(config.MODERATION_CHUNK_OVERLAP, 0), size // 2)
    step = size - overlap
    return [text[start : start + size] for start in range(0, len(text) - overlap, step)]


async def flagged(items: Sequence[Tuple[str, str]]) -> Optional[str]:
    """
    Classify several texts at once; return the kind of the first flagged one, or None

    `items` are (kind, text) pairs, for example ("user_message", original) and
    ("translation", english). Empty texts and repeats are skipped. Every chunk of every text
    is classified concurrently. Raises ModerationError when the classifier fails or the
    texts need more than MODERATION_MAX_CHUNKS chunks in total.
    """
    seen = set()
    work: List[Tuple[str, str]] = []
    for kind, text in items:
        text = text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        work.extend((kind, chunk) for chunk in chunks(text))
    if not work:
        return None
    if len(work) > config.MODERATION_MAX_CHUNKS:
        logger.warning(
            "Moderation input needs %d chunks (limit %d); not classified",
            len(work),
            config.MODERATION_MAX_CHUNKS,
        )
        raise ModerationError("input too long to classify")

    verdicts = await asyncio.gather(*(_classify_one(chunk) for _, chunk in work))
    for (kind, _), injected in zip(work, verdicts, strict=True):
        if injected:
            return kind
    return None


async def classify(text: str) -> bool:
    """
    Classify `text` with Prompt Guard; True means a prompt injection was detected

    Long texts are split into chunks (see `chunks()`); any flagged chunk flags the text.
    The guard model does not need to be listed in the provider's MODELS, and it is never
    used as a chat fallback (see the module docstring).

    Raises ModerationError when the classifier cannot be reached, answers with something
    that can't be interpreted, or the text needs more than MODERATION_MAX_CHUNKS chunks;
    the caller then applies MODERATION_FAIL_MODE.
    """
    return await flagged([("text", text)]) is not None


async def _classify_one(text: str) -> bool:
    """
    Classify one chunk that fits the classifier's context

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


async def screen(items: Sequence[Tuple[str, str]]) -> bool:
    """
    Check texts before they reach a chat model; True means refuse the request

    Applies MODERATION_FAIL_MODE when the classifier fails (fail-closed raises 503), counts
    flags in /metrics by kind, and logs without the text. Returns False when moderation is
    disabled, at no cost.
    """
    if not enabled():
        return False
    try:
        kind = await flagged(items)
    except ModerationError:
        if fail_closed():
            raise HTTPException(status_code=503, detail="Moderation service unavailable") from None
        return False
    if kind is None:
        return False
    metrics.MODERATION_FLAGGED.labels(kind).inc()
    logger.info("Moderation flagged a %s (text not logged)", kind.replace("_", " "))
    return True


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
