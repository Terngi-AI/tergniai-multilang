"""
Language model client that spreads requests over several providers, models and API keys

Order of attempts: providers in the given order, then each provider's models in order,
then that provider's keys in rotation. A key that is rejected (401/403) or rate-limited
(429) is put on cooldown; a model that errors or returns unusable output is skipped.
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, TypeVar

import httpx
from fastapi import HTTPException

import config
from config import LLMProvider
from services.keypool import key_pool, mask, retry_after_seconds

logger = logging.getLogger(__name__)

T = TypeVar("T")
Message = Dict[str, Any]

# MORENA chat markers: single reserved tokens in its vocabulary (see the model card).
# Do not replace them with <|user|>-style strings; that produces degenerate output.
MORENA_USER, MORENA_ASSISTANT = "<reserved_0>", "<reserved_1>"


class _KeyFailed(Exception):
    """The key was rejected or rate-limited; try another key"""

    def __init__(self, cooldown: float, per_model: bool):
        self.cooldown = cooldown
        # Rate limits apply per model (e.g. on Groq); a rejected key is bad for every model
        self.per_model = per_model


class _ModelFailed(Exception):
    """The model can't serve this request; try the next model"""


def is_configured(provider_names: Sequence[str], kind: Optional[str] = None) -> bool:
    """Whether any of the named LLM providers is usable (optionally of a given kind)"""
    return any(
        (p := config.LLM_PROVIDERS.get(name)) is not None
        and p.configured
        and (kind is None or p.kind == kind)
        for name in provider_names
    )


def render_morena_prompt(messages: List[Message]) -> str:
    """Render chat messages in MORENA's format; system text is folded into the first user turn"""
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] in ("user", "assistant") and m.get("content")]
    prompt = ""
    for i, message in enumerate(turns):
        content = message["content"]
        if i == 0 and system:
            content = f"{system}\n\n{content}"
        marker = MORENA_USER if message["role"] == "user" else MORENA_ASSISTANT
        prompt += f"{marker}\n{content}\n"
    return prompt + f"{MORENA_ASSISTANT}\n"


async def _post(url: str, headers: Dict[str, str], body: Dict[str, Any]) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT) as client:
            return await client.post(url, headers=headers, json=body)
    except httpx.HTTPError as e:
        raise _ModelFailed(f"connection error: {type(e).__name__}") from e


def _check_status(response: httpx.Response, provider: str, key: Optional[str]) -> None:
    """Translate HTTP errors into key or model failures"""
    status = response.status_code
    if status == 200:
        return
    label = f"{provider} key {mask(key)}" if key else provider
    if status in (401, 403):
        logger.warning("%s was rejected (%s); skipping it for a while", label, status)
        raise _KeyFailed(config.INVALID_KEY_COOLDOWN_SECONDS, per_model=False)
    if status == 429:
        logger.warning("%s is rate-limited; trying the next key or model", label)
        raise _KeyFailed(
            retry_after_seconds(response.headers.get("retry-after"), config.KEY_COOLDOWN_SECONDS),
            per_model=True,
        )
    logger.warning("%s returned %s: %s", provider, status, response.text[:500])
    raise _ModelFailed(f"HTTP {status}")


async def _call(
    provider: LLMProvider,
    model: str,
    key: Optional[str],
    messages: List[Message],
    json_mode: bool,
    temperature: float,
    max_tokens: Optional[int],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Message:
    """Send one request to one provider/model/key and return the assistant message"""
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    if provider.kind == "morena":
        body: Dict[str, Any] = {
            "prompt": render_morena_prompt(messages),
            "n_predict": max_tokens or 512,
            "temperature": temperature,
            "stop": [MORENA_USER],
            "cache_prompt": True,
        }
        response = await _post(f"{provider.base_url}/completion", headers, body)
        _check_status(response, provider.name, key)
        try:
            return {"role": "assistant", "content": str(response.json()["content"]).strip()}
        except (ValueError, LookupError, TypeError) as e:
            raise _ModelFailed("malformed response") from e

    body = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    response = await _post(f"{provider.base_url}/chat/completions", headers, body)
    _check_status(response, provider.name, key)
    try:
        message = response.json()["choices"][0]["message"]
    except (ValueError, LookupError, TypeError) as e:
        raise _ModelFailed("malformed response") from e
    if not isinstance(message, dict):
        raise _ModelFailed("malformed response")
    return message


async def complete(
    provider_names: Sequence[str],
    messages: List[Message],
    *,
    parse: Callable[[str], T],
    json_mode: bool = False,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
) -> T:
    """
    Generate a completion, trying providers, models and keys until one succeeds

    Args:
        provider_names: LLM provider names, in priority order
        messages: Chat messages
        parse: Turns the generated text into the result; raise ValueError if it is unusable
        json_mode: Ask OpenAI-compatible providers for a JSON object
        temperature: Sampling temperature
        max_tokens: Optional output limit

    Returns:
        The parsed result from the first provider that succeeds
    """
    return await complete_message(
        provider_names,
        messages,
        parse=lambda message: parse(message.get("content") or ""),
        json_mode=json_mode,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def complete_message(
    provider_names: Sequence[str],
    messages: List[Message],
    *,
    parse: Callable[[Message], T],
    tools: Optional[List[Dict[str, Any]]] = None,
    json_mode: bool = False,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
) -> T:
    """
    Like `complete`, but `parse` receives the whole assistant message (including any
    tool calls). When `tools` are given, only OpenAI-compatible providers are used.
    """
    providers = [
        provider
        for name in provider_names
        if (provider := config.LLM_PROVIDERS.get(name)) is not None
        and provider.configured
        and (not tools or provider.kind == "openai")
    ]
    if not providers:
        raise HTTPException(status_code=503, detail="Language model service is not configured")

    # Models that failed for reasons other than rate limits are not retried
    failed: Set[Tuple[str, str]] = set()
    deadline = time.monotonic() + config.RATE_LIMIT_MAX_WAIT_SECONDS

    while True:
        # Shortest wait until a rate-limited key/model becomes usable again
        soonest: Optional[float] = None

        for provider in providers:
            name = provider.name
            keys: List[Optional[str]] = list(key_pool.order(f"llm:{name}", provider.api_keys))
            if not provider.api_keys:
                keys = [None]

            for model in provider.models:
                if (name, model) in failed:
                    continue
                for key in keys:
                    if key and not key_pool.available(key, model):
                        wait = key_pool.wait_time(key, model)
                        soonest = wait if soonest is None else min(soonest, wait)
                        continue
                    try:
                        message = await _call(
                            provider,
                            model,
                            key,
                            messages,
                            json_mode,
                            temperature,
                            max_tokens,
                            tools,
                        )
                    except _KeyFailed as e:
                        if key:
                            key_pool.cool_down(key, e.cooldown, model if e.per_model else None)
                        if e.per_model:
                            soonest = e.cooldown if soonest is None else min(soonest, e.cooldown)
                        continue
                    except _ModelFailed as e:
                        logger.warning("%s/%s failed (%s); trying the next model", name, model, e)
                        failed.add((name, model))
                        break
                    try:
                        return parse(message)
                    except ValueError as e:
                        logger.warning("%s/%s returned unusable output (%s)", name, model, e)
                        failed.add((name, model))
                        break

        # Everything left is rate-limited: wait briefly if a slot frees up soon enough
        if soonest is None or time.monotonic() + soonest > deadline:
            break
        logger.info("All models are rate-limited; waiting %.1fs before retrying", soonest)
        await asyncio.sleep(max(soonest, 0.05))

    raise HTTPException(status_code=502, detail="Error connecting to language model service")


def parse_json_object(text: str) -> Dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences or surrounding text"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in output")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("output is not a JSON object")
    return data
