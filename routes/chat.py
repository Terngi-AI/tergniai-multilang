"""
Conversational chat routes: the agent with server-side memory, plus a web chat page
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

import config
from middleware import authenticated_key, client_id
from models import (
    ChatRequest,
    ChatResponse,
    ConversationDeleteResponse,
    ConversationExport,
    ConversationHistory,
    MemoryMessage,
)
from services import conversations, deadline
from services.agent import run_agent
from services.languages import validate_language

logger = logging.getLogger(__name__)

router = APIRouter()

CHAT_PAGE = Path(__file__).resolve().parent.parent / "static" / "chat.html"

# The chat page's assets, served from the same origin (the allow-list also blocks
# path traversal: only these exact names exist)
STATIC_DIR = CHAT_PAGE.parent
STATIC_FILES = {
    "chat.css": "text/css; charset=utf-8",
    "chat.js": "text/javascript; charset=utf-8",
}


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
    # Bounded so a client that never (or only slowly) reads can't grow memory without
    # limit: once full, `on_event` blocks and the agent's generation is put on hold
    events: asyncio.Queue[Optional[Tuple[str, Dict[str, Any]]]] = asyncio.Queue(
        maxsize=config.STREAM_QUEUE_MAXSIZE
    )

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
            # End-of-stream marker. Never block on it: if the queue is full, the client
            # stopped reading (or the deadline ended the stream), so it would sit unread
            try:
                events.put_nowait(None)
            except asyncio.QueueFull:
                pass

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
                # Wait for the next event, but at most until the next heartbeat: while
                # the agent is silent (e.g. running a slow tool call), a proxy with an
                # idle timeout (Nginx, ALB, ...) would otherwise close the connection
                heartbeat = config.STREAM_HEARTBEAT_SECONDS
                if left is None:
                    wait = heartbeat if heartbeat > 0 else None
                else:
                    wait = min(heartbeat, left) if heartbeat > 0 else left
                try:
                    item = await asyncio.wait_for(events.get(), timeout=wait)
                except TimeoutError:
                    left = deadline.remaining()
                    if left is not None and left <= 0:
                        yield _sse(
                            "error",
                            {"message": "Request deadline exceeded", "status_code": 504},
                        )
                        break
                    # An SSE comment: clients ignore it, but it resets the proxy's
                    # idle timer
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield _sse(*item)
                # done/error is the last event the producer sends, so the stream can end
                # right away instead of waiting for the end-of-stream marker
                if item[0] in ("done", "error"):
                    break
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


@router.get("/v1/chat/{conversation_id}/export", response_model=ConversationExport)
async def export_conversation(conversation_id: str, http_request: Request, response: Response):
    """Download one conversation as a JSON file (data access request)"""
    messages = await conversations.get(conversation_id, client_id(http_request))
    if messages is None:
        raise HTTPException(status_code=404, detail="Conversation not found or expired")
    response.headers["Content-Disposition"] = 'attachment; filename="conversation.json"'
    return ConversationExport(
        conversation_id=conversation_id,
        exported_at=datetime.now(UTC).isoformat(),
        messages=[MemoryMessage.model_validate(message) for message in messages],
    )


@router.delete("/v1/chat", response_model=ConversationDeleteResponse)
async def delete_all_conversations(http_request: Request):
    """
    Delete every conversation belonging to the caller (data erasure request)

    Delete-all is only allowed for callers identified by a valid API key: when no API key
    is sent, ownership would fall back to the client IP, which a NAT or proxy can share
    with other people. Delete single conversations by id instead in that case.
    """
    if authenticated_key(http_request) is None:
        raise HTTPException(
            status_code=403,
            detail=(
                "Delete-all requires a valid API key, so one caller cannot erase chats "
                "sharing the same IP. Delete individual conversations by id instead."
            ),
        )
    deleted = await conversations.delete_all(client_id(http_request))
    return ConversationDeleteResponse(deleted=deleted)


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


@router.get("/static/{name}", include_in_schema=False)
async def chat_static(name: str):
    """The chat page's stylesheet and script (public, like the page itself)"""
    if name not in STATIC_FILES:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(STATIC_DIR / name, media_type=STATIC_FILES[name])
