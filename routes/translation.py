"""
Translation routes for the Terngi Translation API
"""

import logging

from fastapi import APIRouter, HTTPException

from config import MAX_BATCH_CHARACTERS, SUPPORTED_LANGUAGES
from models import (
    BatchTranslationRequest,
    BatchTranslationResponse,
    DetectionRequest,
    DetectionResponse,
    TranslationRequest,
    TranslationResponse,
)
from services.languages import resolve_source_language, validate_language
from services.translator import detect_language, translate_batch, translate_text

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/translate", response_model=TranslationResponse)
async def translate_text_route(request: TranslationRequest):
    """
    Translate text between supported languages (use from_language "auto" to detect the source)
    """
    validate_language(request.to_language, "Target")

    try:
        from_language = await resolve_source_language(request.content, request.from_language)

        # Use the Azure translation service
        translated_text = await translate_text(request.content, from_language, request.to_language)

        return TranslationResponse(
            translated_text=translated_text,
            from_language=from_language,
            to_language=request.to_language,
            original_text=request.content,
        )

    except HTTPException as e:
        raise e  # Re-raise HTTPExceptions
    except Exception as e:
        logger.exception("Unexpected translation error")
        raise HTTPException(status_code=500, detail="Translation error") from e


@router.post("/v1/translate/batch", response_model=BatchTranslationResponse)
async def translate_batch_route(request: BatchTranslationRequest):
    """
    Translate several texts in one request. With "auto", the source language
    is detected from the first text and applied to the whole batch.
    """
    validate_language(request.to_language, "Target")

    if sum(len(text) for text in request.texts) > MAX_BATCH_CHARACTERS:
        raise HTTPException(
            status_code=400,
            detail=f"Batch exceeds {MAX_BATCH_CHARACTERS} characters in total",
        )

    try:
        from_language = await resolve_source_language(request.texts[0], request.from_language)
        translations = await translate_batch(request.texts, from_language, request.to_language)

        return BatchTranslationResponse(
            translations=translations,
            from_language=from_language,
            to_language=request.to_language,
        )

    except HTTPException as e:
        raise e  # Re-raise HTTPExceptions
    except Exception as e:
        logger.exception("Unexpected batch translation error")
        raise HTTPException(status_code=500, detail="Translation error") from e


@router.post("/v1/detect", response_model=DetectionResponse)
async def detect_language_route(request: DetectionRequest):
    """
    Detect the language of a piece of text
    """
    language, score = await detect_language(request.content)

    return DetectionResponse(
        language=language,
        language_name=SUPPORTED_LANGUAGES.get(language),
        score=score,
        is_supported=language in SUPPORTED_LANGUAGES,
    )
