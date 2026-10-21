from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = None
    temperature: Optional[float] = 0.7


class ChatResponse(BaseModel):
    response: str
    model: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None


class TranslateRequest(BaseModel):
    text: str
    target_lang: str
    source_lang: Optional[str] = "auto"


class TranslateResponse(BaseModel):
    translated_text: str
    detected_source_lang: Optional[str] = None


class BatchTranslateRequest(BaseModel):
    texts: List[str]
    target_lang: str
    source_lang: Optional[str] = "auto"


class BatchTranslateResponse(BaseModel):
    translations: List[str]


class DetectRequest(BaseModel):
    text: str


class DetectResponse(BaseModel):
    language: str
    confidence: Optional[float] = None


class AgentRequest(BaseModel):
    task: str
    context: Optional[Dict[str, Any]] = None


class AgentResponse(BaseModel):
    result: Any
    steps_taken: Optional[List[Dict[str, Any]]] = None
