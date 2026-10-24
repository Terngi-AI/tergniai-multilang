"""Deterministic upstream mock used by the load tests.

The app normally talks to Azure Translator, an OpenAI-compatible LLM (Groq by default)
and optionally a local MORENA server. This tiny FastAPI app implements just enough of
those protocols to exercise the real request path without spending provider quota.

Run with:

    uvicorn loadtest.mock_upstream:app --port 9001

Set MOCK_LATENCY_MS to add a fixed delay to every upstream response and simulate a slow
provider. The mock is intentionally dependency-free apart from FastAPI/uvicorn.
"""

import asyncio
import os

from fastapi import FastAPI, Request

app = FastAPI(title="Terngi load-test upstream")

LATENCY_SECONDS = max(0.0, float(os.getenv("MOCK_LATENCY_MS", "0"))) / 1000


async def _wait() -> None:
    if LATENCY_SECONDS:
        await asyncio.sleep(LATENCY_SECONDS)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/translate")
async def translate(request: Request):
    """Azure Translator /translate response shape."""
    body = await request.json()
    to_language = request.query_params.get("to", "unknown")
    texts = [item.get("text", "") for item in body] if isinstance(body, list) else []
    await _wait()
    return [
        {
            "detectedLanguage": {"language": "en", "score": 1.0},
            "translations": [{"text": f"mock[{to_language}]: {text}", "to": to_language}],
        }
        for text in texts
    ]


@app.post("/detect")
async def detect(request: Request):
    """Azure Translator /detect response shape."""
    await request.json()
    await _wait()
    return [{"language": "en", "score": 0.99, "isTranslationSupported": True}]


@app.post("/openai/v1/chat/completions")
async def chat_completion(request: Request):
    """OpenAI-compatible chat completion response shape."""
    body = await request.json()
    await _wait()
    message = {
        "role": "assistant",
        "content": os.getenv("MOCK_CHAT_REPLY", "Mock answer from the load-test model."),
    }
    return {
        "id": "chatcmpl-loadtest",
        "object": "chat.completion",
        "model": body.get("model", "loadtest"),
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
    }


@app.post("/morena/completion")
async def morena_completion(request: Request):
    """llama.cpp /completion response shape used by MORENA."""
    await request.json()
    await _wait()
    return {
        "content": os.getenv("MOCK_MORENA_REPLY", "Mock MORENA translation."),
        "stop": True,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "loadtest.mock_upstream:app",
        host="127.0.0.1",
        port=int(os.getenv("MOCK_PORT", "9001")),
        reload=False,
    )
