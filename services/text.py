"""
Unicode helpers

NFC keeps composed and decomposed spellings identical, so Yoruba and Igbo tone marks
(and every other combining character) produce the same cache keys and comparisons.
"""

import unicodedata
from typing import Any


def normalize_text(text: str) -> str:
    """Return the NFC form of a piece of text"""
    return unicodedata.normalize("NFC", text)


def normalize_value(value: Any) -> Any:
    """Pydantic before-validator: normalise strings, leave other values untouched"""
    return normalize_text(value) if isinstance(value, str) else value
