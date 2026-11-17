"""
Typed request and response models, mirroring the Terngi AI API (see GET /openapi.json)
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

# --- Requests ------------------------------------------------------------------------------


class Message(BaseModel):
    """A previous turn in a conversation"""

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    language: str = "auto"
    reply_language: Optional[str] = None


class TranslateRequest(BaseModel):
    content: str
    from_language: str = "auto"
    to_language: str


class BatchTranslateRequest(BaseModel):
    texts: List[str]
    from_language: str = "auto"
    to_language: str


class DetectRequest(BaseModel):
    content: str


class AgentRequest(BaseModel):
    message: str
    language: str = "auto"
    reply_language: Optional[str] = None
    history: Optional[List[Message]] = None


# --- Responses -----------------------------------------------------------------------------


class AgentStep(BaseModel):
    """A tool the assistant ran while answering"""

    tool: str
    arguments: Any = None
    output: Dict[str, Any] = {}


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    language: str
    reply_language: str
    steps: List[AgentStep] = []


class Conversation(BaseModel):
    conversation_id: str
    messages: List[Message]


class TranslateResponse(BaseModel):
    translated_text: str
    from_language: str
    to_language: str
    original_text: str


class BatchTranslateResponse(BaseModel):
    translations: List[str]
    from_language: str
    to_language: str


class DetectResponse(BaseModel):
    language: str
    language_name: Optional[str] = None
    score: float
    is_supported: bool


class AgentResponse(BaseModel):
    answer: str
    language: str
    reply_language: str
    steps: List[AgentStep] = []


class StreamEvent(BaseModel):
    """
    One Server-Sent Event from POST /v1/chat/stream

    event is "start", "token", "discard", "tool", "done" or "error". For "done", show
    data["reply"]: it is the final text and can differ from the streamed tokens.
    """

    event: str
    data: Dict[str, Any]
