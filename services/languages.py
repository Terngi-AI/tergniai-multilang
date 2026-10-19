"""
Language validation helpers shared by the routes
"""

from fastapi import HTTPException

from config import SUPPORTED_LANGUAGES
from services.translator import detect_language

AUTO = "auto"


def validate_language(code: str, role: str) -> None:
    """Raise a 400 error if `code` is not a supported language"""
    if code not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{role} language '{code}' not supported. "
                f"Use one of: {list(SUPPORTED_LANGUAGES.keys())}"
            ),
        )


async def resolve_source_language(content: str, from_language: str) -> str:
    """
    Return the source language, detecting it first when `from_language` is "auto"
    """
    if from_language == AUTO:
        detected, _ = await detect_language(content)
        if detected not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Detected language '{detected}' is not supported. "
                    f"Use one of: {list(SUPPORTED_LANGUAGES.keys())}"
                ),
            )
        return detected

    validate_language(from_language, "Source")
    return from_language
