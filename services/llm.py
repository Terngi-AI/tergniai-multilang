"""
Language model client that spreads requests over several providers, models and API keys

Order of attempts: providers in the given order, then each provider's models in order,
then that provider's keys in rotation. A key that is rejected (401/403) or rate-limited
(429) is put on cooldown; a model that errors or returns unusable output is skipped.
"""

import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple, TypeVar

import httpx
from fastapi import HTTPException

import config
import metrics
from config import LLMProvider
from services import deadline, usage
from services.keypool import key_pool, mask, retry_after_seconds
from services.retry import RETRY_STATUS_CODES, error_summary, retry_delay

logger = logging.getLogger(__name__)

T = TypeVar("T")
Message = Dict[str, Any]
# Receives each piece of generated text as it streams in
OnToken = Callable[[str], Awaitable[None]]

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

    def __init__(self, reason: str, unreachable: bool = False):
        super().__init__(reason)
        # The provider's server couldn't be reached at all, so its other models won't work either
        self.unreachable = unreachable


def _provider_slot(name: str) -> str:
    """Key-pool slot used to rest a provider whose server is unreachable"""
    return f"provider:{name}"


def is_available(name: str) -> bool:
    """Whether a provider is configured and not resting after being unreachable"""
    provider = config.LLM_PROVIDERS.get(name)
    return provider is not None and provider.configured and key_pool.available(_provider_slot(name))


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
    """
    POST with exponential-backoff retries for transient 5xx and connection errors.
    429s are returned as-is: they are handled by rotating keys and models instead.
    """
    attempt = 0
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT) as client:
        while True:
            deadline.consume_attempt()
            try:
                response = await client.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=deadline.timeout(config.REQUEST_TIMEOUT),
                )
            except httpx.HTTPError as e:
                delay = retry_delay(attempt, None) if isinstance(e, httpx.TransportError) else None
                if delay is None or attempt >= config.UPSTREAM_MAX_RETRIES:
                    raise _ModelFailed(
                        f"connection error: {type(e).__name__}", unreachable=True
                    ) from e
                reason = type(e).__name__
            else:
                status = response.status_code
                if status == 429 or status not in RETRY_STATUS_CODES:
                    return response
                delay = retry_delay(attempt, response)
                if delay is None or attempt >= config.UPSTREAM_MAX_RETRIES:
                    return response
                reason = str(status)

            attempt += 1
            logger.warning(
                "%s %s, retrying in %.2fs (retry %d/%d)",
                url,
                reason,
                delay,
                attempt,
                config.UPSTREAM_MAX_RETRIES,
            )
            await deadline.sleep(delay)


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
    # The provider's error *message* can quote the user's text, so above DEBUG we log
    # only the status and the provider's error code/type, plus the request ID
    request_id = deadline.request_id()
    logger.warning(
        "%s returned %s (%s)%s",
        provider,
        status,
        error_summary(response),
        f" [{request_id}]" if request_id else "",
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s returned %s, body: %s", provider, status, response.text[:500])
    raise _ModelFailed(f"HTTP {status}")


async def _stream_chat(
    url: str,
    headers: Dict[str, str],
    body: Dict[str, Any],
    provider: str,
    key: Optional[str],
    on_token: OnToken,
) -> Message:
    """
    POST a streaming chat completion, forward content deltas to `on_token` and return the
    assembled assistant message (content plus any tool calls built up from their deltas)
    """
    content: List[str] = []
    tool_calls: Dict[int, Dict[str, Any]] = {}
    stream_usage: Dict[str, int] = {}
    deadline.consume_attempt()
    try:
        async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=body,
                timeout=deadline.timeout(config.REQUEST_TIMEOUT),
            ) as response:
                if response.status_code != 200:
                    await response.aread()
                    _check_status(response, provider, key)
                async for line in response.aiter_lines():
                    deadline.check()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        usage_chunk = chunk.get("usage")
                        if isinstance(usage_chunk, dict):
                            stream_usage = usage_chunk
                        delta = chunk["choices"][0].get("delta") or {}
                    except (ValueError, LookupError, TypeError):
                        continue  # keep-alives and provider-specific extras
                    text = delta.get("content")
                    if text:
                        content.append(text)
                        await on_token(text)
                    for part in delta.get("tool_calls") or []:
                        call = tool_calls.setdefault(
                            part.get("index", len(tool_calls)),
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        call["id"] = part.get("id") or call["id"]
                        function = part.get("function") or {}
                        call["function"]["name"] += function.get("name") or ""
                        call["function"]["arguments"] += function.get("arguments") or ""
    except httpx.HTTPError as e:
        raise _ModelFailed(f"connection error: {type(e).__name__}", unreachable=True) from e

    await usage.record_upstream(
        prompt_tokens=stream_usage.get("prompt_tokens", 0),
        completion_tokens=stream_usage.get("completion_tokens", 0),
    )
    message: Message = {"role": "assistant", "content": "".join(content)}
    if tool_calls:
        message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
    return message


async def _call(
    provider: LLMProvider,
    model: str,
    key: Optional[str],
    messages: List[Message],
    json_mode: bool,
    temperature: float,
    max_tokens: Optional[int],
    tools: Optional[List[Dict[str, Any]]] = None,
    on_token: Optional[OnToken] = None,
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
            data = response.json()
            message = {"role": "assistant", "content": str(data["content"]).strip()}
        except (ValueError, LookupError, TypeError) as e:
            raise _ModelFailed("malformed response") from e
        await usage.record_upstream(
            prompt_tokens=data.get("tokens_evaluated", 0),
            completion_tokens=data.get("tokens_predicted", 0),
        )
        return message

    body = {"model": model, "messages": messages, "temperature": temperature}
    if max_tokens:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if on_token is not None:
        body["stream"] = True
        return await _stream_chat(
            f"{provider.base_url}/chat/completions", headers, body, provider.name, key, on_token
        )
    response = await _post(f"{provider.base_url}/chat/completions", headers, body)
    _check_status(response, provider.name, key)
    try:
        data = response.json()
        message = data["choices"][0]["message"]
        usage_data = data.get("usage") or {}
    except (ValueError, LookupError, TypeError) as e:
        raise _ModelFailed("malformed response") from e
    if not isinstance(message, dict):
        raise _ModelFailed("malformed response")
    await usage.record_upstream(
        prompt_tokens=usage_data.get("prompt_tokens", 0),
        completion_tokens=usage_data.get("completion_tokens", 0),
    )
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
    on_token: Optional[OnToken] = None,
    model: Optional[str] = None,
) -> T:
    """
    Like `complete`, but `parse` receives the whole assistant message (including any
    tool calls). When `tools` are given, only OpenAI-compatible providers are used.

    With `on_token`, the response is streamed and each piece of text is passed to it as it
    arrives. Fallback to another model or provider only happens before the first token;
    after that a failure is final, so the caller never receives text from two models.

    With `model`, only that model name is tried (across the given providers); providers
    that don't offer it are skipped. This is used for classifier models such as Prompt Guard.
    """
    providers = [
        provider
        for name in provider_names
        if (provider := config.LLM_PROVIDERS.get(name)) is not None
        and provider.configured
        and (model is None or model in provider.models)
        and (not tools or provider.kind == "openai")
        and (on_token is None or provider.kind == "openai")
    ]
    emitted = False

    async def forward(text: str) -> None:
        nonlocal emitted
        emitted = True
        if on_token is not None:
            await on_token(text)

    if not providers:
        raise HTTPException(status_code=503, detail="Language model service is not configured")

    # Models that failed for reasons other than rate limits are not retried
    failed: Set[Tuple[str, str]] = set()
    wait_until = time.monotonic() + config.RATE_LIMIT_MAX_WAIT_SECONDS

    while True:
        deadline.check()
        # Shortest wait until a rate-limited key/model becomes usable again
        soonest: Optional[float] = None

        for provider in providers:
            name = provider.name
            if not key_pool.available(_provider_slot(name)):
                continue  # recently unreachable; don't pay for the connection timeout again
            keys: List[Optional[str]] = list(key_pool.order(f"llm:{name}", provider.api_keys))
            if not provider.api_keys:
                keys = [None]

            for provider_model in provider.models:
                if model is not None and provider_model != model:
                    continue
                if not key_pool.available(_provider_slot(name)):
                    break
                if (name, provider_model) in failed:
                    continue
                for key in keys:
                    if key and not key_pool.available(key, provider_model):
                        wait = key_pool.wait_time(key, provider_model)
                        soonest = wait if soonest is None else min(soonest, wait)
                        continue
                    deadline.check()
                    try:
                        with metrics.track_upstream(name):
                            message = await _call(
                                provider,
                                provider_model,
                                key,
                                messages,
                                json_mode,
                                temperature,
                                max_tokens,
                                tools,
                                forward if on_token is not None else None,
                            )
                    except (_KeyFailed, _ModelFailed) as e:
                        if emitted:
                            logger.warning("%s/%s failed mid-stream (%s)", name, provider_model, e)
                            raise HTTPException(
                                status_code=502, detail="Language model stream was interrupted"
                            ) from e
                        if isinstance(e, _ModelFailed):
                            logger.warning(
                                "%s/%s failed (%s); trying the next model",
                                name,
                                provider_model,
                                e,
                            )
                            failed.add((name, provider_model))
                            if e.unreachable:
                                logger.warning(
                                    "%s is unreachable; skipping it for %.0fs",
                                    name,
                                    config.PROVIDER_DOWN_COOLDOWN_SECONDS,
                                )
                                key_pool.cool_down(
                                    _provider_slot(name), config.PROVIDER_DOWN_COOLDOWN_SECONDS
                                )
                            break

                        if key:
                            key_pool.cool_down(
                                key, e.cooldown, provider_model if e.per_model else None
                            )
                        if e.per_model:
                            soonest = e.cooldown if soonest is None else min(soonest, e.cooldown)
                        continue
                    deadline.check()
                    try:
                        return parse(message)
                    except ValueError as e:
                        if emitted:
                            raise HTTPException(
                                status_code=502, detail="Language model returned unusable output"
                            ) from e
                        logger.warning(
                            "%s/%s returned unusable output (%s)", name, provider_model, e
                        )
                        failed.add((name, provider_model))
                        break

        # Everything left is rate-limited: wait briefly if a slot frees up soon enough
        if soonest is None or time.monotonic() + soonest > wait_until:
            break
        logger.info("All models are rate-limited; waiting %.1fs before retrying", soonest)
        await deadline.sleep(max(soonest, 0.05))

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
