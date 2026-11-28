"""
Cheap output checks for LLM translations (#144)

An LLM translation that reads fluently can still be wrong in ways that hurt people: "take 2
tablets" becomes "take 3 tablets", a link or an amount is dropped, or the model adds
"Here is the translation:" or a note of its own. These checks run on every LLM translation.
A failure counts as unusable output, so the next model or provider is tried. When none
passes, the translator returns the candidate with the fewest problems, marked unverified.

Numbers are compared as digit strings, whatever the script (Arabic-Indic, Devanagari...) and
separators ("5,000" and "5000" match). Models often write numbers as words ("márùn-ún" for 5),
so a source number that is missing only counts when the translation still uses digits: then
the model is clearly writing digits and has dropped or changed one. A number that appears in
the translation but not the source always counts.

Problems are named (e.g. "number", "preamble"), never quoted, so logs never contain user text.
"""

import re
import unicodedata
from collections import Counter
from contextvars import ContextVar
from typing import List, Optional, Sequence, Tuple

import config

# Digits, optionally grouped by separators: 5,000 / 10:30 / 2.5 / 1 000 000
_NUMBER = re.compile(r"\d+(?:[.,:   ]\d+)*")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Text a model adds around a translation
_PREAMBLE = re.compile(
    r"^\s*(?:here(?:'s| is) (?:the|your|my) (?:translation|translated)|"
    r"(?:the )?translation(?: is)?\s*:|translated text\s*:|"
    r"(?:sure|certainly|of course)[,!.]?\s+here)",
    re.IGNORECASE,
)
_TRAILING_NOTE = re.compile(r"\n\s*\(?\s*(?:note|translator'?s note)\s*:", re.IGNORECASE)
# Scripts that take far fewer characters than Latin text for the same meaning
_DENSE_SCRIPTS = {"zh-Hans", "zh-Hant", "ja", "ko", "yue", "lzh"}
# Below this many characters the length ratio says nothing
_MIN_LENGTH_FOR_RATIO = 20


def _digits(text: str) -> List[str]:
    """Every number in the text as plain ASCII digits, separators removed"""
    ascii_text = "".join(
        str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch for ch in text
    )
    return [re.sub(r"\D", "", match) for match in _NUMBER.findall(ascii_text)]


def number_problem(source: str, translation: str) -> bool:
    """A number was changed, added, or dropped while other numbers stayed as digits"""
    expected, found = Counter(_digits(source)), Counter(_digits(translation))
    if found - expected:
        return True  # a number the source doesn't have, e.g. 2 became 3
    return bool(expected - found) and bool(found)


def link_problem(source: str, translation: str) -> bool:
    """A URL or e-mail address from the source is missing or altered"""
    for pattern in (_URL, _EMAIL):
        for value in pattern.findall(source):
            if value.rstrip(".,;:!?") not in translation:
                return True
    return False


def commentary_problem(source: str, translation: str) -> bool:
    """The model introduced or annotated the translation instead of just giving it"""
    if _PREAMBLE.search(translation) and not _PREAMBLE.search(source):
        return True
    return bool(_TRAILING_NOTE.search(translation)) and not _TRAILING_NOTE.search(source)


def length_problem(source: str, translation: str, target: str) -> bool:
    """The translation is far longer, or far shorter, than the source"""
    if len(source.strip()) < _MIN_LENGTH_FOR_RATIO:
        return False
    ratio = len(translation.strip()) / len(source.strip())
    if ratio > config.TRANSLATION_MAX_LENGTH_RATIO:
        return True
    return target not in _DENSE_SCRIPTS and ratio < config.TRANSLATION_MIN_LENGTH_RATIO


def problems(source: str, translation: str, target: str) -> List[str]:
    """Names of the checks one translation fails (empty when it passes)"""
    if not config.TRANSLATION_CHECKS:
        return []
    found = []
    if number_problem(source, translation):
        found.append("number")
    if link_problem(source, translation):
        found.append("link")
    if commentary_problem(source, translation):
        found.append("commentary")
    if length_problem(source, translation, target):
        found.append("length")
    return found


# --- Candidates kept for when every provider fails the checks -----------------------------

# (problem count, translations) offered by providers whose output failed the checks, for the
# current translate_batch call; None outside one
_candidates: ContextVar[Optional[List[Tuple[int, List[str]]]]] = ContextVar(
    "translation_candidates", default=None
)


def collect():
    """Start collecting rejected candidates; returns the token to pass to stop()"""
    return _candidates.set([])


def stop(token) -> None:
    _candidates.reset(token)


def offer(problem_count: int, translations: Sequence[str]) -> None:
    """Keep a rejected translation in case nothing better turns up"""
    collected = _candidates.get()
    if collected is not None:
        collected.append((problem_count, list(translations)))


def best_candidate() -> Optional[List[str]]:
    """The rejected candidate with the fewest problems (the earliest on a tie), if any"""
    collected = _candidates.get()
    if not collected:
        return None
    return min(collected, key=lambda item: item[0])[1]
