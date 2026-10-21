"""
Conversational chat routes: the agent with server-side memory, plus a web chat page
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from middleware import client_id
from models import ChatRequest, ChatResponse, ConversationHistory, MemoryMessage
from services import conversations
from services.agent import run_agent
from services.languages import validate_language

logger = logging.getLogger(__name__)

router = APIRouter()

CHAT_PAGE = Path(__file__).resolve().parent.parent / "static" / "chat.html"


@router.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request):
    """
    Chat with Terngi AI. Send a message (in any supported language) and, to continue a
    conversation, the conversation_id from the previous reply. The server remembers the
    conversation, so there is no need to send history.
    """
    if request.reply_language is not None:
        validate_language(request.reply_language, "Reply")

    owner = client_id(http_request)
    if request.conversation_id:
        history = await conversations.get(request.conversation_id, owner)
        if history is None:
            raise HTTPException(status_code=404, detail="Conversation not found or expired")
        conversation_id = request.conversation_id
    else:
        history = []
        conversation_id = await conversations.create(owner)

    try:
        result = await run_agent(
            request.message,
            language=request.language,
            reply_language=request.reply_language,
            history=history,
        )
    except HTTPException as e:
        raise e  # Re-raise HTTPExceptions
    except Exception as e:
        logger.exception("Unexpected chat error")
        raise HTTPException(status_code=500, detail="Chat error") from e

    await conversations.append(
        conversation_id,
        owner,
        {"role": "user", "content": request.message},
        {"role": "assistant", "content": result["answer"]},
    )

    return ChatResponse(
        conversation_id=conversation_id,
        reply=result["answer"],
        language=result["language"],
        reply_language=result["reply_language"],
        steps=result["steps"],
    )


@router.get("/v1/chat/{conversation_id}", response_model=ConversationHistory)
async def get_conversation(conversation_id: str, http_request: Request):
    """Return the messages of a conversation"""
    messages = await conversations.get(conversation_id, client_id(http_request))
    if messages is None:
        raise HTTPException(status_code=404, detail="Conversation not found or expired")
    return ConversationHistory(
        conversation_id=conversation_id,
        messages=[MemoryMessage.model_validate(message) for message in messages],
    )


@router.delete("/v1/chat/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, http_request: Request):
    """Forget a conversation"""
    if not await conversations.delete(conversation_id, client_id(http_request)):
        raise HTTPException(status_code=404, detail="Conversation not found or expired")
    return Response(status_code=204)


@router.get("/chat", response_class=HTMLResponse, include_in_schema=False)
async def chat_page():
    """Web chat interface"""
    return HTMLResponse(CHAT_PAGE.read_text(encoding="utf-8"))
