"""
Conversation routes for the Terngi Translation API
"""

import logging

from fastapi import APIRouter, HTTPException

from models import ConversationRequest, ConversationResponse
from services.assistant import get_response
from services.languages import resolve_source_language, validate_language
from services.translator import translate_text

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/converse", response_model=ConversationResponse)
async def converse(request: ConversationRequest):
    """
    Translate text and get contextual response using Groq LLM

    Language flow:
    - English to Nigerian language: Keep input in English, get English response from Groq, translate to target language
    - Nigerian language to English: Translate input to English, get English response from Groq, keep in English
    - Nigerian language to Nigerian language: Translate input to English, get English response from Groq, translate to target language
    - from_language "auto": detect the source language first, then follow the flow above
    """
    validate_language(request.to_language, "Target")

    try:
        from_language = await resolve_source_language(request.content, request.from_language)

        # Content to pass to Groq (will be in English)
        groq_input = ""

        # Step 1: Prepare the input for Groq based on source language
        if from_language == "en":
            # If input is already English, use it directly
            groq_input = request.content
            translated_text = await translate_text(request.content, "en", request.to_language)
        else:
            # If input is not English, translate it to English first
            groq_input = await translate_text(request.content, from_language, "en")
            translated_text = await translate_text(
                request.content, from_language, request.to_language
            )

        # Step 2: Get response from Groq (always in English)
        memory_context = (
            [message.model_dump() for message in request.memory_context]
            if request.memory_context
            else None
        )
        groq_response = await get_response(groq_input, memory_context)

        # Step 3: Prepare final response based on target language
        final_response = ""
        if request.to_language == "en":
            # If target is English, use Groq response directly
            final_response = groq_response
        else:
            # If target is not English, translate Groq response
            final_response = await translate_text(groq_response, "en", request.to_language)

        return ConversationResponse(
            translated_text=translated_text,
            from_language=from_language,
            to_language=request.to_language,
            original_text=request.content,
            response=final_response,
        )

    except HTTPException as e:
        raise e  # Re-raise HTTPExceptions
    except Exception as e:
        logger.exception("Unexpected conversation error")
        raise HTTPException(status_code=500, detail="Conversation error") from e
