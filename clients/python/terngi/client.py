from types import TracebackType
from typing import Any, Dict, List, Optional, Type
import httpx
from pydantic import BaseModel

from .exceptions import APIResponseError, AuthenticationError
from .models import (
    AgentRequest,
    AgentResponse,
    BatchTranslateRequest,
    BatchTranslateResponse,
    ChatRequest,
    ChatResponse,
    DetectRequest,
    DetectResponse,
    TranslateRequest,
    TranslateResponse,
)


class TerngiClient:
    """Synchronous typed client for Terngi AI API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "terngi-python-sdk/0.1.0",
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.Client(
            base_url=self.base_url,
            headers=self.headers,
            timeout=timeout,
        )

    def _post(self, path: str, payload: BaseModel) -> Dict[str, Any]:
        resp = self._client.post(path, json=payload.model_dump(exclude_none=True))
        if resp.status_code == 401:
            raise AuthenticationError("Invalid or missing API key.")
        if resp.is_error:
            raise APIResponseError(resp.status_code, resp.text)
        return resp.json()

    def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = 0.7,
    ) -> ChatResponse:
        req = ChatRequest(prompt=prompt, system_prompt=system_prompt, temperature=temperature)
        return ChatResponse(**self._post("/chat", req))

    def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = "auto",
    ) -> TranslateResponse:
        req = TranslateRequest(text=text, target_lang=target_lang, source_lang=source_lang)
        return TranslateResponse(**self._post("/translate", req))

    def translate_batch(
        self,
        texts: List[str],
        target_lang: str,
        source_lang: Optional[str] = "auto",
    ) -> BatchTranslateResponse:
        req = BatchTranslateRequest(texts=texts, target_lang=target_lang, source_lang=source_lang)
        return BatchTranslateResponse(**self._post("/translate_batch", req))

    def detect(self, text: str) -> DetectResponse:
        req = DetectRequest(text=text)
        return DetectResponse(**self._post("/detect", req))

    def agent(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        req = AgentRequest(task=task, context=context)
        return AgentResponse(**self._post("/agent", req))

    def close(self) -> None:
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
