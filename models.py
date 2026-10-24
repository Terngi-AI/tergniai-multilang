"""
Pydantic models for the Terngi Translation API
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

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

MAX_GLOSSARY_TERMS = 100
MAX_GLOSSARY_TERM_LENGTH = 200


def normalize_glossary(value: Any) -> Any:
    """Normalise every term and translation to NFC before validating the glossary"""
    if not isinstance(value, dict):
        return value

    normalized: Dict[str, Any] = {}
    for source, translation in value.items():
        if not isinstance(source, str):
            return value
        source = normalize_value(source)
        if not source.strip():
            raise ValueError("glossary terms must not be empty")
        if isinstance(translation, str):
            normalized[source] = normalize_value(translation)
        elif isinstance(translation, dict):
            normalized[source] = {
                str(language): normalize_value(text) for language, text in translation.items()
            }
        else:
            normalized[source] = translation
    return normalized


GlossaryTranslation = Annotated[str, Field(min_length=1, max_length=MAX_CONTENT_LENGTH)]
GlossaryByLanguage = Annotated[Dict[str, GlossaryTranslation], Field(min_length=1, max_length=100)]
GlossaryValue = Union[GlossaryTranslation, GlossaryByLanguage]
Glossary = Annotated[
    Dict[
        Annotated[str, Field(min_length=1, max_length=MAX_GLOSSARY_TERM_LENGTH)],
        GlossaryValue,
    ],
    BeforeValidator(normalize_glossary),
    Field(max_length=MAX_GLOSSARY_TERMS),
]


class TranslationRequest(BaseModel):
    """Request model for translation endpoints"""

    content: Text
    from_language: str = Field(..., description='Language code, or "auto" to detect it')
    to_language: str
    glossary: Optional[Glossary] = Field(
        None, description="Terms to protect or translate consistently, e.g. {'Terngi': 'Terngi'}"
    )


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
    glossary: Optional[Glossary] = Field(
        None, description="Terms to protect or translate consistently, e.g. {'Terngi': 'Terngi'}"
    )


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


class FeedbackRequest(BaseModel):
    """A good/bad rating for a translation or chat reply (opt-in only)"""

    source_text: Text
    translated_text: Text
    from_language: str
    to_language: str
    provider: str = Field(..., min_length=1, max_length=100)
    rating: Literal["good", "bad"]
    correction: Optional[StoredText] = Field(
        None, description="An optional better translation supplied by the user"
    )
    consent: bool = Field(
        False,
        description=(
            "Must be true. Confirms that the feedback may be stored and published as part "
            "of the open evaluation set."
        ),
    )


class FeedbackResponse(BaseModel):
    """Confirmation that feedback was appended to storage"""

    status: Literal["stored"] = "stored"


class UsageStats(BaseModel):
    """Usage counters for one API key on one UTC day"""

    date: str
    requests: int
    upstream_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageResponse(BaseModel):
    """Usage for the calling API key (issue #47)"""

    usage: List[UsageStats]
    quota: Optional[int] = Field(
        default=None, description="Daily request quota for this key, if any"
    )
    remaining: Optional[int] = Field(
        default=None, description="Requests left today before the quota"
    )
    resets_at: Optional[str] = Field(default=None, description="When the daily quota resets (UTC)")


class ConversationExport(BaseModel):
    """A conversation downloaded for a data-access request"""

    conversation_id: str
    exported_at: str
    messages: List[MemoryMessage]


class ConversationDeleteResponse(BaseModel):
    """How many of the caller's conversations were deleted"""

    deleted: int


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
