"""
Pydantic models for the Terngi Translation API
"""

from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, BeforeValidator, Field

from config import MAX_BATCH_SIZE, MAX_CONTENT_LENGTH, MAX_MEMORY_MESSAGES
from services.text import normalize_value

# User-provided text is normalised before length validation, so an NFD spelling cannot
# reject a value whose composed form fits. Responses use the same form.
NfcText = Annotated[str, BeforeValidator(normalize_value)]
StoredText = Annotated[str, BeforeValidator(normalize_value), Field(max_length=MAX_CONTENT_LENGTH)]
Text = Annotated[
    str,
    BeforeValidator(normalize_value),
    Field(min_length=1, max_length=MAX_CONTENT_LENGTH),
]


class TranslationRequest(BaseModel):
    """Request model for translation endpoints"""

    content: Text
    from_language: str = Field(..., description='Language code, or "auto" to detect it')
    to_language: str


class TranslationResponse(BaseModel):
    """Response model for translation endpoints"""

    translated_text: NfcText
    from_language: str
    to_language: str
    original_text: NfcText


class MemoryMessage(BaseModel):
    """A previous turn in the conversation (system messages are not allowed)"""

    role: Literal["user", "assistant"]
    content: StoredText


class ConversationRequest(BaseModel):
    """Request model for conversation endpoints"""

    content: Text
    from_language: str = Field(..., description='Language code, or "auto" to detect it')
    to_language: str
    memory_context: Optional[List[MemoryMessage]] = Field(
        default=None, max_length=MAX_MEMORY_MESSAGES
    )


class ConversationResponse(BaseModel):
    """Response model for conversation endpoints"""

    translated_text: NfcText
    from_language: str
    to_language: str
    original_text: NfcText
    response: Optional[NfcText] = None


class BatchTranslationRequest(BaseModel):
    """Request model for translating several texts at once"""

    texts: List[Text] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)
    from_language: str = Field(..., description='Language code, or "auto" to detect it')
    to_language: str


class BatchTranslationResponse(BaseModel):
    """Response model for batch translation"""

    translations: List[NfcText]
    from_language: str
    to_language: str


class DetectionRequest(BaseModel):
    """Request model for language detection"""

    content: Text


class DetectionResponse(BaseModel):
    """Response model for language detection"""

    language: str
    language_name: Optional[str] = None
    score: float
    is_supported: bool


class AgentRequest(BaseModel):
    """Request model for the agent endpoint"""

    message: Text
    language: str = Field("auto", description='Language of the message, or "auto" to detect it')
    reply_language: Optional[str] = Field(
        None, description="Language for the answer; defaults to the message's language"
    )
    history: Optional[List[MemoryMessage]] = Field(default=None, max_length=MAX_MEMORY_MESSAGES)


class AgentStep(BaseModel):
    """A tool call made by the agent"""

    tool: str
    arguments: Any
    output: Dict[str, Any]


class AgentResponse(BaseModel):
    """Response model for the agent endpoint"""

    answer: NfcText
    language: str
    reply_language: str
    steps: List[AgentStep]


class ChatRequest(BaseModel):
    """Request model for the chat endpoint"""

    message: Text
    conversation_id: Optional[str] = Field(
        None, description="Continue this conversation; omit to start a new one"
    )
    language: str = Field("auto", description='Language of the message, or "auto" to detect it')
    reply_language: Optional[str] = Field(
        None, description="Language for the reply; defaults to the message's language"
    )


class ChatResponse(BaseModel):
    """Response model for the chat endpoint"""

    conversation_id: str
    reply: NfcText
    language: str
    reply_language: str
    steps: List[AgentStep]


class ConversationHistory(BaseModel):
    """A stored conversation"""

    conversation_id: str
    messages: List[MemoryMessage]


class WhatsAppTemplate(BaseModel):
    """An approved WhatsApp template (needed to message someone first, or after 24 hours)"""

    name: str = Field(..., min_length=1, max_length=512)
    language: str = Field("en", description="The template's WhatsApp language code, e.g. en_GB")
    parameters: List[str] = Field(default_factory=list, description="Values for its body variables")


class WhatsAppSendRequest(BaseModel):
    """Send a WhatsApp message, optionally translated into the recipient's language"""

    to: str = Field(..., description="Phone number with country code, e.g. +447700900123")
    text: Optional[
        Annotated[
            str,
            BeforeValidator(normalize_value),
            Field(min_length=1, max_length=20000),
        ]
    ] = None
    from_language: str = Field("en", description="Language of `text`")
    to_language: Optional[str] = Field(
        None, description="Translate `text` into this language first"
    )
    template: Optional[WhatsAppTemplate] = None


class WhatsAppSendResponse(BaseModel):
    to: str
    message_ids: List[str]
    text: Optional[str] = None
