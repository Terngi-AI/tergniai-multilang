"""
Conversational chat routes: the agent with server-side memory, plus a web chat page
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse

from middleware import client_id
from models import ChatRequest, ChatResponse, ConversationHistory, MemoryMessage
from services import conversations, deadline
from services.agent import run_agent
from services.languages import validate_language

logger = logging.getLogger(__name__)

router = APIRouter()

CHAT_PAGE = Path(__file__).resolve().parent.parent / "static" / "chat.html"


async def _open_conversation(request: ChatRequest, owner: str) -> Tuple[str, List[Dict[str, str]]]:
    """Validate the request and return (conversation_id, history), starting a new chat if needed"""
    if request.reply_language is not None:
        validate_language(request.reply_language, "Reply")

    if request.conversation_id:
        history = await conversations.get(request.conversation_id, owner)
        if history is None:
            raise HTTPException(status_code=404, detail="Conversation not found or expired")
        return request.conversation_id, history
    return await conversations.create(owner), []


def _sse(event: str, data: Dict[str, Any]) -> str:
    """Format one Server-Sent Event"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request):
    """
    Chat with Terngi AI. Send a message (in any supported language) and, to continue a
    conversation, the conversation_id from the previous reply. The server remembers the
    conversation, so there is no need to send history.
    """
    owner = client_id(http_request)
    conversation_id, history = await _open_conversation(request, owner)

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

    deadline.check()
    await conversations.append(
        conversation_id,
        owner,
        {"role": "user", "content": request.message},
        {"role": "assistant", "content": result["answer"]},
    )
    deadline.check()

    return ChatResponse(
        conversation_id=conversation_id,
        reply=result["answer"],
        language=result["language"],
        reply_language=result["reply_language"],
        steps=result["steps"],
    )


@router.post("/v1/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request):
    """
    Like POST /v1/chat, but streams the reply as Server-Sent Events while it is generated:

    - `start`: `{"conversation_id"}`
    - `token`: `{"text"}`, a piece of the reply, in order
    - `discard`: drop the text streamed so far (the model is calling a tool instead)
    - `tool`: `{"tool", "ok"}`, a tool the assistant ran
    - `done`: `{"conversation_id", "reply", "language", "reply_language", "steps"}`.
      `reply` is the final, authoritative text; show it in place of the streamed text
    - `error`: `{"message", "status_code"}`
    """
    owner = client_id(http_request)
    conversation_id, history = await _open_conversation(request, owner)
    events: asyncio.Queue[Optional[Tuple[str, Dict[str, Any]]]] = asyncio.Queue()

    async def on_event(event: str, data: Dict[str, Any]) -> None:
        await events.put((event, data))

    async def run() -> None:
        try:
            result = await run_agent(
                request.message,
                language=request.language,
                reply_language=request.reply_language,
                history=history,
                on_event=on_event,
            )
            deadline.check()
            await conversations.append(
                conversation_id,
                owner,
                {"role": "user", "content": request.message},
                {"role": "assistant", "content": result["answer"]},
            )
            deadline.check()
            await events.put(
                (
                    "done",
                    {
                        "conversation_id": conversation_id,
                        "reply": result["answer"],
                        "language": result["language"],
                        "reply_language": result["reply_language"],
                        "steps": result["steps"],
                    },
                )
            )
        except HTTPException as e:
            await events.put(("error", {"message": e.detail, "status_code": e.status_code}))
        except Exception:
            logger.exception("Unexpected chat error")
            await events.put(("error", {"message": "Chat error", "status_code": 500}))
        finally:
            await events.put(None)

    async def stream() -> AsyncIterator[str]:
        task = asyncio.create_task(run())
        try:
            yield _sse("start", {"conversation_id": conversation_id})
            while True:
                left = deadline.remaining()
                if left is not None and left <= 0:
                    yield _sse(
                        "error",
                        {"message": "Request deadline exceeded", "status_code": 504},
                    )
                    break
                try:
                    item = (
                        await asyncio.wait_for(events.get(), timeout=left)
                        if left is not None
                        else await events.get()
                    )
                except TimeoutError:
                    yield _sse(
                        "error",
                        {"message": "Request deadline exceeded", "status_code": 504},
                    )
                    break
                if item is None:
                    break
                yield _sse(*item)
        finally:
            if not task.done():  # the client went away: stop generating
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
