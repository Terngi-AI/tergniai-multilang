"""
Conversation routes for the Terngi Translation API
"""

import logging

from fastapi import APIRouter, HTTPException

import config
from models import ConversationRequest, ConversationResponse
from services import llm
from services.assistant import get_native_response, get_response
from services.languages import resolve_source_language, validate_language
from services.translator import translate_text

logger = logging.getLogger(__name__)

router = APIRouter()


def _native_providers(from_language: str, to_language: str) -> list:
    """
    The providers in NATIVE_CHAT_PROVIDERS that can take this conversation as it is

    A provider must be usable now and list its languages explicitly, both of them among
    them: one with no list means "any language", which is not a promise to speak this one.
    """
    names = []
    for name in config.NATIVE_CHAT_PROVIDERS:
        provider = config.LLM_PROVIDERS.get(name)
        if (
            provider is not None
            and provider.languages is not None
            and provider.supports(from_language, to_language)
            and llm.is_available(name)
        ):
            names.append(name)
    return names


@router.post("/v1/converse", response_model=ConversationResponse)
async def converse(request: ConversationRequest):
    """
    Translate text and get contextual response using Groq LLM

    Language flow:
    - English to Nigerian language: Keep input in English, get English response from Groq, translate to target language
    - Nigerian language to English: Translate input to English, get English response from Groq, keep in English
    - Nigerian language to Nigerian language: Translate input to English, get English response from Groq, translate to target language
    - from_language "auto": detect the source language first, then follow the flow above

    With NATIVE_CHAT_PROVIDERS set, a provider that speaks both languages answers directly in the
    target language instead (no translation to English and back); if it fails, the flows above run.
    """
    validate_language(request.to_language, "Target")

    try:
        from_language = await resolve_source_language(request.content, request.from_language)

        memory_context = (
            [message.model_dump() for message in request.memory_context]
            if request.memory_context
            else None
        )

        native = _native_providers(from_language, request.to_language)
        if native:
            try:
                native_response = await get_native_response(
                    request.content, request.to_language, native, memory_context
                )
            except HTTPException as e:
                logger.warning(
                    "Native chat failed (%s); using the translation pipeline", e.status_code
                )
            else:
                return ConversationResponse(
                    translated_text=await translate_text(
                        request.content, from_language, request.to_language
                    ),
                    from_language=from_language,
                    to_language=request.to_language,
                    original_text=request.content,
                    response=native_response,
                )

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
