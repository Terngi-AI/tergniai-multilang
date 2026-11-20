"""
Personal-data patterns shared by the API and scripts/redact_pii.py

Two operations use the same patterns, so they can't drift apart:

- `redact()` replaces personal data with fixed labels ([EMAIL], [URL], [PHONE], [ID]) for
  data that is stored or published, such as feedback records (#141).
- `mask()` / `unmask()` swap personal data for numbered placeholders ([[P1]], [[P2]], ...)
  before text is sent to a third-party provider and put the real values back afterwards
  (PII_MASKING, #142).

The patterns err on the side of over-matching: masking a date-like order number is
acceptable, missing a phone number is not.
"""

import re
from typing import Callable, Dict, List, Match, Sequence, Tuple

# https://example.com/path, www.example.org/tz, ...
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
# amina.yusuf+work@gmail.com, chidi_okeke@yahoo.co.uk, ...
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# +234 803 123 4567, +2348031234567, +233 24 123 4567, ...
_PHONE_INTL = re.compile(r"(?<!\d)\+\d{1,3}(?:[\s.-]?\d){7,14}(?!\d)")
# Local numbers without a country code: 0803 123 4567, 024 123 4567, (0803) 123-4567
_PHONE_LOCAL = re.compile(r"(?<!\d)(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}(?:[\s.-]\d{2,4}){1,4}(?!\d)")
# A date such as 2026-10-25: phone-shaped but not one
_DATE = re.compile(r"\d{4}[-/. ]\d{1,2}[-/. ]\d{1,2}")
# Consecutive digit strings of 11+ (Nigerian BVN is 11 digits)
_LONG_DIGITS = re.compile(r"(?<!\d)\d{11,}(?!\d)")

# Masking placeholders. Models sometimes add spaces inside the brackets; accept those.
_PLACEHOLDER = re.compile(r"\[\[\s*P(\d+)\s*\]\]")


def _is_phone(value: str) -> bool:
    """Dates and short numbers are phone-shaped but kept"""
    if _DATE.fullmatch(value):
        return False
    return len(re.sub(r"\D", "", value)) >= 7


# (pattern, label, filter) in the order they are applied: URLs and e-mails first, so the
# digits inside them are not matched as phone numbers
_RULES: List[Tuple[re.Pattern[str], str, Callable[[str], bool]]] = [
    (_URL, "[URL]", lambda _: True),
    (_EMAIL, "[EMAIL]", lambda _: True),
    (_PHONE_INTL, "[PHONE]", _is_phone),
    (_PHONE_LOCAL, "[PHONE]", _is_phone),
    (_LONG_DIGITS, "[ID]", lambda _: True),
]


def _apply(text: str, replace: Callable[[str, str], str]) -> str:
    """Run every rule over the text; `replace(value, label)` returns the substitute"""
    for pattern, label, keep in _RULES:

        def substitute(match: Match[str], label: str = label, keep=keep) -> str:
            value = match.group(0)
            return replace(value, label) if keep(value) else value

        text = pattern.sub(substitute, text)
    return text


def redact_names(text: str, names: Sequence[str]) -> str:
    """Mask a list of known person names (longest first, case-insensitive)"""
    for name in sorted(names, key=len, reverse=True):
        pattern = r"\b" + re.escape(name) + r"\b"
        text = re.sub(pattern, "[NAME]", text, flags=re.IGNORECASE)
    return text


def redact(text: str, names: Sequence[str] = ()) -> str:
    """Replace e-mails, URLs, phone numbers, long digit strings and known names with labels"""
    return redact_names(_apply(text, lambda _value, label: label), names)


def mask(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Replace personal data with numbered placeholders

    Returns the masked text and a map of placeholder -> original value. The same value gets
    the same placeholder. Numbering starts above any placeholder-like token already in the
    text, so a user's own "[[P1]]" is never overwritten on restore.
    """
    existing = [int(number) for number in _PLACEHOLDER.findall(text)]
    counter = max(existing, default=0)
    by_value: Dict[str, str] = {}

    def replace(value: str, _label: str) -> str:
        nonlocal counter
        if value not in by_value:
            counter += 1
            by_value[value] = f"[[P{counter}]]"
        return by_value[value]

    masked = _apply(text, replace)
    return masked, {marker: value for value, marker in by_value.items()}


def _number(marker: str) -> str:
    return marker[3:-2]


def unmask(text: str, replacements: Dict[str, str]) -> str:
    """Put the original values back in place of the placeholders"""
    if not replacements:
        return text
    values = {_number(marker): value for marker, value in replacements.items()}

    def restore(match: Match[str]) -> str:
        return values.get(match.group(1), match.group(0))

    return _PLACEHOLDER.sub(restore, text)


def missing(text: str, replacements: Dict[str, str]) -> List[str]:
    """Placeholders that a provider dropped from its reply"""
    present = set(_PLACEHOLDER.findall(text))
    return [marker for marker in replacements if _number(marker) not in present]
