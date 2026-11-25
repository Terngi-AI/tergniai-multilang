"""
Conversation routes for the Terngi Translation API
"""

import logging

from fastapi import APIRouter, HTTPException

import config
from models import ConversationRequest, ConversationResponse
from services import moderation
from services.assistant import get_response
from services.languages import resolve_source_language, validate_language
from services.translator import translate_text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conversation"])


@router.post("/v1/converse", response_model=ConversationResponse)
async def converse(request: ConversationRequest):
    """
    Translate text and get contextual response using Groq LLM

    Language flow:
    - English to Nigerian language: Keep input in English, get English response from Groq, translate to target language
    - Nigerian language to English: Translate input to English, get English response from Groq, keep in English
    - Nigerian language to Nigerian language: Translate input to English, get English response from Groq, translate to target language
    - from_language "auto": detect the source language first, then follow the flow above

    `memory_context` is written by the caller, so the model is told it may not be genuine.
    With prompt-injection moderation on, the message, its English translation and the
    history are classified before the chat model is called; a flagged request gets a polite
    refusal as its `response`. Operators can reject client-written assistant turns with
    `CONVERSE_ALLOW_ASSISTANT_HISTORY=false` (400).
    """
    validate_language(request.to_language, "Target")
    if not config.CONVERSE_ALLOW_ASSISTANT_HISTORY and any(
        message.role == "assistant" for message in request.memory_context or []
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "This server does not accept assistant turns in memory_context. Send only "
                "the user's own earlier messages, or use /v1/chat for server-side history."
            ),
        )

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
        # Moderation (#38, #169): the message, its English rendering and the client-written
        # history together. History is joined into one text so many short turns don't use
        # up the classifier budget one chunk each.
        history = "\n\n".join(message["content"] for message in memory_context or [])
        if await moderation.screen(
            [
                ("user_message", request.content),
                ("translation", groq_input),
                ("history", history),
            ]
        ):
            return ConversationResponse(
                translated_text=translated_text,
                from_language=from_language,
                to_language=request.to_language,
                original_text=request.content,
                response=await moderation.refusal(request.to_language),
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
