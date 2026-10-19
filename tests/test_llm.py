"""
Tests for multi-provider, multi-model, multi-key language model calls
"""

import json

import httpx
import pytest
import respx
from fastapi import HTTPException

import config
from services import assistant, llm
from services.keypool import KeyPool, key_pool

GROQ = "https://api.groq.com/openai/v1"
OPENROUTER = "https://openrouter.ai/api/v1"
MORENA = "http://localhost:8080"


def provider(name, base_url, keys=("k1",), models=("m1",), kind="openai", requires_key=True):
    return config.LLMProvider(
        name=name,
        kind=kind,
        base_url=base_url,
        api_keys=tuple(keys),
        models=tuple(models),
        requires_key=requires_key,
    )


def reply(text="Hello!") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def sent(call) -> dict:
    return json.loads(call.request.content)


@pytest.fixture
def providers(monkeypatch):
    def configure(*items):
        monkeypatch.setattr(config, "LLM_PROVIDERS", {p.name: p for p in items})
        monkeypatch.setattr(config, "CHAT_PROVIDERS", [p.name for p in items])

    return configure


@respx.mock
async def test_chat_builds_messages(providers):
    providers(provider("groq", GROQ))
    route = respx.post(GROQ + "/chat/completions").mock(return_value=reply())

    answer = await assistant.get_response(
        "Hi",
        [
            {"role": "user", "content": "earlier"},
            {"role": "system", "content": "should be dropped"},
        ],
    )

    assert answer == "Hello!"
    messages = sent(route.calls.last)["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "user"]
    assert messages[0]["content"] == config.SYSTEM_PROMPT


@respx.mock
async def test_keys_rotate_between_requests(providers):
    providers(provider("groq", GROQ, keys=("key-a", "key-b")))
    route = respx.post(GROQ + "/chat/completions").mock(return_value=reply())

    await assistant.get_response("one")
    await assistant.get_response("two")

    used = [c.request.headers["Authorization"] for c in route.calls]
    assert used == ["Bearer key-a", "Bearer key-b"]


@respx.mock
async def test_rate_limited_key_falls_through_to_next_key(providers):
    providers(provider("groq", GROQ, keys=("key-a", "key-b")))
    route = respx.post(GROQ + "/chat/completions").mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "120"}), reply("ok")]
    )

    assert await assistant.get_response("hi") == "ok"
    assert [c.request.headers["Authorization"] for c in route.calls] == [
        "Bearer key-a",
        "Bearer key-b",
    ]
    # key-a is cooling down, so the next request goes straight to key-b
    route.side_effect = None
    route.return_value = reply("again")
    await assistant.get_response("hi")
    await assistant.get_response("hi")
    assert all(c.request.headers["Authorization"] == "Bearer key-b" for c in route.calls[2:])


@respx.mock
async def test_revoked_key_is_skipped(providers):
    providers(provider("groq", GROQ, keys=("revoked", "good")))
    route = respx.post(GROQ + "/chat/completions").mock(
        side_effect=lambda request: (
            httpx.Response(401)
            if request.headers["Authorization"] == "Bearer revoked"
            else reply("ok")
        )
    )

    for _ in range(3):
        assert await assistant.get_response("hi") == "ok"
    revoked_calls = [
        c for c in route.calls if c.request.headers["Authorization"] == "Bearer revoked"
    ]
    assert len(revoked_calls) == 1


@respx.mock
async def test_falls_back_to_next_model(providers):
    providers(provider("groq", GROQ, models=("retired-model", "good-model")))
    route = respx.post(GROQ + "/chat/completions").mock(
        side_effect=lambda request: (
            httpx.Response(404, json={"error": "model_not_found"})
            if sent_model(request) == "retired-model"
            else reply("ok")
        )
    )

    assert await assistant.get_response("hi") == "ok"
    assert [json.loads(c.request.content)["model"] for c in route.calls] == [
        "retired-model",
        "good-model",
    ]


def sent_model(request) -> str:
    return json.loads(request.content)["model"]


@respx.mock
async def test_falls_back_to_next_provider(providers):
    providers(provider("groq", GROQ), provider("openrouter", OPENROUTER))
    respx.post(GROQ + "/chat/completions").mock(return_value=httpx.Response(503))
    backup = respx.post(OPENROUTER + "/chat/completions").mock(return_value=reply("backup"))

    assert await assistant.get_response("hi") == "backup"
    assert backup.called


@respx.mock
async def test_connection_error_falls_back(providers):
    providers(provider("groq", GROQ), provider("openrouter", OPENROUTER))
    respx.post(GROQ + "/chat/completions").mock(side_effect=httpx.ConnectTimeout("slow"))
    respx.post(OPENROUTER + "/chat/completions").mock(return_value=reply("backup"))

    assert await assistant.get_response("hi") == "backup"


@respx.mock
async def test_all_providers_failing_returns_502(providers):
    providers(provider("groq", GROQ, keys=("a", "b"), models=("m1", "m2")))
    route = respx.post(GROQ + "/chat/completions").mock(return_value=httpx.Response(500))

    with pytest.raises(HTTPException) as exc_info:
        await assistant.get_response("hi")

    assert exc_info.value.status_code == 502
    # Each model gets the first try plus UPSTREAM_MAX_RETRIES; keys aren't retried for a 5xx
    assert route.call_count == 2 * (1 + config.UPSTREAM_MAX_RETRIES)


async def test_unconfigured_providers_return_503(providers):
    providers(provider("groq", GROQ, keys=()))

    with pytest.raises(HTTPException) as exc_info:
        await assistant.get_response("hi")

    assert exc_info.value.status_code == 503


@respx.mock
async def test_all_keys_cooling_down_skips_provider(providers):
    providers(provider("groq", GROQ, keys=("a",)), provider("openrouter", OPENROUTER))
    key_pool.cool_down("a", 300)
    groq = respx.post(GROQ + "/chat/completions")
    respx.post(OPENROUTER + "/chat/completions").mock(return_value=reply("backup"))

    assert await assistant.get_response("hi") == "backup"
    assert not groq.called


@respx.mock
async def test_empty_reply_tries_next_model(providers):
    providers(provider("groq", GROQ, models=("m1", "m2")))
    respx.post(GROQ + "/chat/completions").mock(side_effect=[reply("   "), reply("real answer")])

    assert await assistant.get_response("hi") == "real answer"


# --- MORENA (llama.cpp) ------------------------------------------------------


def morena_provider():
    return provider(
        "morena",
        MORENA,
        keys=(),
        models=("morena-1.5b-instruct",),
        kind="morena",
        requires_key=False,
    )


def test_morena_prompt_format():
    prompt = llm.render_morena_prompt(
        [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Bye"},
        ]
    )

    assert prompt == (
        "<reserved_0>\nBe brief.\n\nHi\n<reserved_1>\nHello\n<reserved_0>\nBye\n<reserved_1>\n"
    )


@respx.mock
async def test_morena_translates_one_text_at_a_time(providers):
    providers(morena_provider())
    route = respx.post(MORENA + "/completion").mock(
        side_effect=[
            httpx.Response(200, json={"content": " Ẹ kú àárọ̀ \n"}),
            httpx.Response(200, json={"content": "Ẹ ṣé"}),
        ]
    )

    result = await assistant.translate_batch(["Good morning", "Thank you"], "en", "yo", "morena")

    assert result == ["Ẹ kú àárọ̀", "Ẹ ṣé"]
    body = sent(route.calls[0])
    assert body["prompt"].startswith(
        "<reserved_0>\nTranslate the following text from English to Yoruba"
    )
    assert body["prompt"].endswith("Good morning\n<reserved_1>\n")
    assert body["stop"] == ["<reserved_0>"]
    assert "Authorization" not in route.calls[0].request.headers


@respx.mock
async def test_morena_failure_falls_back_to_next_provider(providers):
    providers(morena_provider(), provider("groq", GROQ))
    respx.post(MORENA + "/completion").mock(side_effect=httpx.ConnectError("server not running"))
    respx.post(GROQ + "/chat/completions").mock(return_value=reply("from groq"))

    assert await assistant.get_response("hi") == "from groq"


def test_morena_not_used_for_detection_by_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq,morena")
    monkeypatch.delenv("DETECTION_PROVIDERS", raising=False)
    monkeypatch.delenv("TRANSLATION_PROVIDERS", raising=False)
    import importlib

    fresh = importlib.reload(config)
    try:
        assert fresh.DETECTION_PROVIDERS == ["azure", "groq"]
        assert fresh.TRANSLATION_PROVIDERS == ["azure", "groq", "morena"]
        assert fresh.LLM_PROVIDERS["morena"].configured
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# --- Configuration -------------------------------------------------------------


def test_provider_config_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq,openrouter,custom")
    monkeypatch.setenv("GROQ_API_KEYS", "g1, g2")
    monkeypatch.setenv("GROQ_API_KEY", "g2")
    monkeypatch.setenv("GROQ_MODELS", "a,b")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o1")
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://llm.example.com/v1/")
    monkeypatch.setenv("CUSTOM_MODEL", "my-model")
    monkeypatch.setenv("CUSTOM_API_KEY", "c1")
    import importlib

    fresh = importlib.reload(config)
    try:
        groq = fresh.LLM_PROVIDERS["groq"]
        assert groq.api_keys == ("g1", "g2")
        assert groq.models == ("a", "b")
        assert not fresh.LLM_PROVIDERS["openrouter"].configured  # no model given
        custom = fresh.LLM_PROVIDERS["custom"]
        assert custom.base_url == "https://llm.example.com/v1"
        assert custom.configured
        assert fresh.CHAT_PROVIDERS == ["groq", "openrouter", "custom"]
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_key_pool_rotation_and_cooldown(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("services.keypool.time.monotonic", lambda: now[0])
    pool = KeyPool()

    assert pool.order("s", ["a", "b", "c"]) == ["a", "b", "c"]
    assert pool.order("s", ["a", "b", "c"]) == ["b", "c", "a"]
    pool.cool_down("c", 10)
    assert pool.order("s", ["a", "b", "c"]) == ["a", "b"]
    now[0] = 11
    assert "c" in pool.order("s", ["a", "b", "c"])


@respx.mock
async def test_rate_limit_only_blocks_that_model(providers):
    # Groq rate limits are per model: a 429 on one model must not block the key for others
    providers(provider("groq", GROQ, keys=("only-key",), models=("big", "small")))
    route = respx.post(GROQ + "/chat/completions").mock(
        side_effect=lambda request: (
            httpx.Response(429, headers={"retry-after": "60"})
            if sent_model(request) == "big"
            else reply("from small")
        )
    )

    assert await assistant.get_response("hi") == "from small"
    assert await assistant.get_response("again") == "from small"
    # "big" was skipped on the second request while cooling down
    assert [sent_model(c.request) for c in route.calls] == ["big", "small", "small"]


@respx.mock
async def test_revoked_key_is_skipped_for_every_model(providers):
    providers(provider("groq", GROQ, keys=("revoked", "good"), models=("m1", "m2")))
    route = respx.post(GROQ + "/chat/completions").mock(
        side_effect=lambda request: (
            httpx.Response(401)
            if request.headers["Authorization"] == "Bearer revoked"
            else httpx.Response(500)
            if sent_model(request) == "m1"
            else reply("ok")
        )
    )

    assert await assistant.get_response("hi") == "ok"
    revoked = [c for c in route.calls if c.request.headers["Authorization"] == "Bearer revoked"]
    assert len(revoked) == 1


@respx.mock
async def test_waits_briefly_when_everything_is_rate_limited(providers, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_MAX_WAIT_SECONDS", 5)
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        key_pool.reset()  # time passes: the cooldown is over

    monkeypatch.setattr("services.llm.asyncio.sleep", fake_sleep)
    providers(provider("groq", GROQ, keys=("only-key",), models=("m1",)))
    respx.post(GROQ + "/chat/completions").mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "2"}), reply("after waiting")]
    )

    assert await assistant.get_response("hi") == "after waiting"
    assert slept == [2.0]


@respx.mock
async def test_does_not_wait_beyond_the_limit(providers, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_MAX_WAIT_SECONDS", 5)
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("services.llm.asyncio.sleep", fake_sleep)
    providers(provider("groq", GROQ, keys=("only-key",), models=("m1",)))
    respx.post(GROQ + "/chat/completions").mock(
        return_value=httpx.Response(429, headers={"retry-after": "60"})
    )

    with pytest.raises(HTTPException) as exc_info:
        await assistant.get_response("hi")

    assert exc_info.value.status_code == 502
    assert slept == []
