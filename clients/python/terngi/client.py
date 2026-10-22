import json
from types import TracebackType
from typing import Any, Dict, Iterator, List, Optional, Type

import httpx
from pydantic import BaseModel

from .exceptions import APIResponseError, AuthenticationError, RateLimitError
from .models import (
    AgentRequest,
    AgentResponse,
    BatchTranslateRequest,
    BatchTranslateResponse,
    ChatRequest,
    ChatResponse,
    Conversation,
    DetectRequest,
    DetectResponse,
    Message,
    StreamEvent,
    TranslateRequest,
    TranslateResponse,
)

__version__ = "0.1.0"


class TerngiClient:
    """Synchronous typed client for the Terngi AI API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "http://localhost:8000",
        timeout: float = 120.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        """
        Args:
            api_key: Sent as the X-API-Key header (only needed if the server sets API_KEYS)
            base_url: Where the API runs
            timeout: Seconds to wait for a response; chat and agent calls can take a while
            http_client: Use your own httpx.Client (e.g. for proxies or tests). It is not
                closed by this client.
        """
        headers = {"User-Agent": f"terngi-python-sdk/{__version__}"}
        if api_key:
            headers["X-API-Key"] = api_key

        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self._client.headers.update(headers)

    # --- HTTP helpers ----------------------------------------------------------------------

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if not response.is_error:
            return
        try:
            message = str(response.json().get("message", response.text))
        except ValueError:
            message = response.text
        status = response.status_code
        if status == 401:
            raise AuthenticationError(status, message)
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(status, message, float(retry_after) if retry_after else None)
        raise APIResponseError(status, message)

    def _request(self, method: str, path: str, payload: Optional[BaseModel] = None) -> Any:
        body = payload.model_dump(exclude_none=True) if payload is not None else None
        response = self._client.request(method, path, json=body)
        self._raise_for_status(response)
        return response.json() if response.content else None

    # --- Endpoints -------------------------------------------------------------------------

    def languages(self) -> Dict[str, str]:
        """Supported language codes and names"""
        return self._request("GET", "/v1/languages")["languages"]

    def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        language: str = "auto",
        reply_language: Optional[str] = None,
    ) -> ChatResponse:
        """
        Chat with Terngi AI. Pass the conversation_id from a previous reply to continue that
        conversation; the server remembers the history.
        """
        req = ChatRequest(
            message=message,
            conversation_id=conversation_id,
            language=language,
            reply_language=reply_language,
        )
        return ChatResponse(**self._request("POST", "/v1/chat", req))

    def chat_stream(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        language: str = "auto",
        reply_language: Optional[str] = None,
    ) -> Iterator[StreamEvent]:
        """
        Like chat(), but yields events while the reply is generated. Print "token" events'
        data["text"] as they arrive, and use data["reply"] from the final "done" event.
        """
        req = ChatRequest(
            message=message,
            conversation_id=conversation_id,
            language=language,
            reply_language=reply_language,
        )
        with self._client.stream(
            "POST", "/v1/chat/stream", json=req.model_dump(exclude_none=True)
        ) as response:
            if response.is_error:
                response.read()
                self._raise_for_status(response)
            event = "message"
            data = ""
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data += line[len("data:") :].strip()
                elif not line and data:
                    yield StreamEvent(event=event, data=json.loads(data))
                    event, data = "message", ""
            if data:
                yield StreamEvent(event=event, data=json.loads(data))

    def get_conversation(self, conversation_id: str) -> Conversation:
        """The messages of a conversation started with chat()"""
        return Conversation(**self._request("GET", f"/v1/chat/{conversation_id}"))

    def delete_conversation(self, conversation_id: str) -> None:
        """Forget a conversation"""
        self._request("DELETE", f"/v1/chat/{conversation_id}")

    def translate(
        self, content: str, to_language: str, from_language: str = "auto"
    ) -> TranslateResponse:
        """Translate text; from_language "auto" detects the source language"""
        req = TranslateRequest(
            content=content, from_language=from_language, to_language=to_language
        )
        return TranslateResponse(**self._request("POST", "/v1/translate", req))

    def translate_batch(
        self, texts: List[str], to_language: str, from_language: str = "auto"
    ) -> BatchTranslateResponse:
        """Translate several texts in one request; results keep the input order"""
        req = BatchTranslateRequest(
            texts=texts, from_language=from_language, to_language=to_language
        )
        return BatchTranslateResponse(**self._request("POST", "/v1/translate/batch", req))

    def detect(self, content: str) -> DetectResponse:
        """Detect the language of a text"""
        return DetectResponse(**self._request("POST", "/v1/detect", DetectRequest(content=content)))

    def agent(
        self,
        message: str,
        language: str = "auto",
        reply_language: Optional[str] = None,
        history: Optional[List[Message]] = None,
    ) -> AgentResponse:
        """The assistant without server-side memory: pass earlier turns in history"""
        req = AgentRequest(
            message=message, language=language, reply_language=reply_language, history=history
        )
        return AgentResponse(**self._request("POST", "/v1/agent", req))

    # --- Lifecycle -------------------------------------------------------------------------

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TerngiClient":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.close()
