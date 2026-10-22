"""
Tests for streaming chat (POST /v1/chat/stream) and streamed LLM calls
"""

import json

import httpx
import pytest
import respx

import config
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"


def sse(*deltas) -> bytes:
    """An OpenAI-compatible streaming body made of the given deltas"""
    lines = [f"data: {json.dumps({'choices': [{'delta': d}]})}\n\n" for d in deltas]
    return ("".join(lines) + "data: [DONE]\n\n").encode()


def stream_reply(*deltas) -> httpx.Response:
    return httpx.Response(200, content=sse(*deltas), headers={"content-type": "text/event-stream"})


def tool_call_fragments(name: str, arguments: dict, call_id: str = "call_1"):
    """A tool call split across several deltas, as providers stream them"""
    args = json.dumps(arguments)
    half = len(args) // 2
    return [
        {"tool_calls": [{"index": 0, "id": call_id, "function": {"name": name, "arguments": ""}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": args[:half]}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": args[half:]}}]},
    ]


def events(response) -> list:
    """Parse a Server-Sent Events body into [(event, data), ...]"""
    parsed = []
    for block in response.text.strip().split("\n\n"):
        event, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        parsed.append((event, json.loads(data)))
    return parsed


def ask(client, message="Hi", **extra):
    return client.post("/v1/chat/stream", json={"message": message, "language": "en", **extra})


@respx.mock
def test_reply_is_streamed_token_by_token(client):
    route = respx.post(CHAT_URL).mock(
        return_value=stream_reply({"content": "Hello"}, {"content": ", Ada"}, {"content": "!"})
    )

    response = ask(client, "I'm Ada")

    assert response.headers["content-type"].startswith("text/event-stream")
    got = events(response)
    assert [e for e, _ in got] == ["start", "token", "token", "token", "done"]
    assert "".join(d["text"] for e, d in got if e == "token") == "Hello, Ada!"
    done = got[-1][1]
    assert done["reply"] == "Hello, Ada!"
    assert done["conversation_id"] == got[0][1]["conversation_id"]
    assert json.loads(route.calls.last.request.content)["stream"] is True

    # The conversation is saved like a normal chat
    history = client.get(f"/v1/chat/{done['conversation_id']}").json()["messages"]
    assert [m["content"] for m in history] == ["I'm Ada", "Hello, Ada!"]


@respx.mock
def test_tool_calls_are_assembled_from_fragments(client):
    respx.post(CHAT_URL).mock(
        side_effect=[
            stream_reply(*tool_call_fragments("list_languages", {})),
            stream_reply({"content": "We support "}, {"content": "96 languages."}),
        ]
    )

    got = events(ask(client, "Which languages?"))

    assert [e for e, _ in got] == ["start", "tool", "token", "token", "done"]
    assert got[1][1] == {"tool": "list_languages", "ok": True}
    done = got[-1][1]
    assert done["reply"] == "We support 96 languages."
    assert done["steps"][0]["tool"] == "list_languages"
    assert "pcm" in done["steps"][0]["output"]["languages"]


@respx.mock
def test_text_before_a_tool_call_is_discarded(client):
    respx.post(CHAT_URL).mock(
        side_effect=[
            stream_reply({"content": "Let me check…"}, *tool_call_fragments("list_languages", {})),
            stream_reply({"content": "Done."}),
        ]
    )

    got = events(ask(client))

    assert [e for e, _ in got] == ["start", "token", "discard", "tool", "token", "done"]
    assert got[-1][1]["reply"] == "Done."


@respx.mock
def test_falls_back_to_next_model_before_the_first_token(client, monkeypatch):
    monkeypatch.setattr(config, "UPSTREAM_MAX_RETRIES", 0)
    groq = config.LLM_PROVIDERS["groq"]
    monkeypatch.setattr(
        config,
        "LLM_PROVIDERS",
        {"groq": config.LLMProvider(**{**groq.__dict__, "models": ("broken", "working")})},
    )
    route = respx.post(CHAT_URL).mock(
        side_effect=lambda request: (
            httpx.Response(500)
            if json.loads(request.content)["model"] == "broken"
            else stream_reply({"content": "From the backup model."})
        )
    )

    got = events(ask(client))

    assert got[-1] == ("done", got[-1][1])
    assert got[-1][1]["reply"] == "From the backup model."
    assert route.call_count == 2


class FailsMidStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield sse({"content": "Half a sen"})[: -len(b"data: [DONE]\n\n")]
        raise httpx.ReadError("connection dropped")

    async def aclose(self):
        pass


@respx.mock
def test_failure_mid_stream_is_reported_not_retried(client, monkeypatch):
    groq = config.LLM_PROVIDERS["groq"]
    monkeypatch.setattr(
        config,
        "LLM_PROVIDERS",
        {"groq": config.LLMProvider(**{**groq.__dict__, "models": ("m1", "m2")})},
    )
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, stream=FailsMidStream()))

    got = events(ask(client))

    assert [e for e, _ in got] == ["start", "token", "error"]
    assert got[-1][1]["status_code"] == 502
    assert route.call_count == 1  # no second model: the user already saw text from the first


def test_unknown_conversation_is_rejected_before_streaming(client):
    response = ask(client, conversation_id="nope")

    assert response.status_code == 404
    assert response.json()["error"] is True


def test_errors_are_sent_as_events(client, monkeypatch):
    monkeypatch.setattr(config, "AGENT_PROVIDERS", [])

    got = events(ask(client))

    assert [e for e, _ in got] == ["start", "error"]
    assert got[1][1] == {"message": "Agent is not configured", "status_code": 503}


@pytest.mark.asyncio
async def test_non_streaming_calls_are_unchanged():
    from services import assistant

    with respx.mock:
        route = respx.post(CHAT_URL).mock(
            return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Hi"}}]})
        )
        assert await assistant.get_response("Hello") == "Hi"
        assert "stream" not in json.loads(route.calls.last.request.content)


def test_chat_page_uses_streaming(client):
    assert "/v1/chat/stream" in client.get("/chat").text
