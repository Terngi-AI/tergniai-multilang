"""
Tests for the multilingual tool-using agent
"""

import json

import httpx
import pytest
import respx

import config
from services import agent
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"
TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"
DETECT_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/detect"


def answer(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": text}}]}
    )


def tool_call(name: str, arguments: dict, call_id: str = "call_1") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(arguments)},
                            }
                        ],
                    }
                }
            ]
        },
    )


def azure_translation(text: str) -> httpx.Response:
    return httpx.Response(200, json=[{"translations": [{"text": text}]}])


def ask(client, **payload):
    return client.post("/v1/agent", json={"language": "en", **payload})


@respx.mock
def test_agent_answers_directly(client):
    route = respx.post(CHAT_URL).mock(return_value=answer("Abuja is the capital of Nigeria."))

    response = ask(client, message="What is the capital of Nigeria?")

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Abuja is the capital of Nigeria."
    assert body["steps"] == []
    sent = json.loads(route.calls.last.request.content)
    assert {t["function"]["name"] for t in sent["tools"]} == set(agent.TOOLS)
    assert sent["tool_choice"] == "auto"


@respx.mock
def test_agent_uses_translate_tool(client):
    respx.post(TRANSLATE_URL).mock(return_value=azure_translation("Sawubona"))
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call(
                "translate", {"text": "Hello", "target_language": "zu", "source_language": "en"}
            ),
            answer('In isiZulu, "hello" is "Sawubona".'),
        ]
    )

    response = ask(client, message="How do I say hello in Zulu?")

    body = response.json()
    assert body["answer"] == 'In isiZulu, "hello" is "Sawubona".'
    assert body["steps"] == [
        {
            "tool": "translate",
            "arguments": {"text": "Hello", "target_language": "zu", "source_language": "en"},
            "output": {"translation": "Sawubona", "source_language": "en", "target_language": "zu"},
        }
    ]
    # The tool result is sent back to the model, linked to the call id
    second = json.loads(route.calls[1].request.content)["messages"]
    assert second[-2]["tool_calls"][0]["id"] == "call_1"
    assert second[-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": json.dumps(body["steps"][0]["output"], ensure_ascii=False),
    }


@respx.mock
def test_agent_understands_african_input_and_replies_in_it(client):
    respx.post(DETECT_URL).mock(
        return_value=httpx.Response(200, json=[{"language": "yo", "score": 0.99}])
    )
    respx.post(TRANSLATE_URL).mock(
        side_effect=[
            azure_translation("Good morning, how are you?"),
            azure_translation("Mo wà dáadáa"),
        ]
    )
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call(
                "translate", {"text": "I am fine", "target_language": "yo", "source_language": "en"}
            ),
            answer("Mo wà dáadáa"),
        ]
    )

    response = client.post("/v1/agent", json={"message": "Ẹ káàrọ̀, ṣé dáadáa ni?"})

    body = response.json()
    assert body["language"] == "yo"
    assert body["reply_language"] == "yo"
    assert body["answer"] == "Mo wà dáadáa"
    first = json.loads(route.calls[0].request.content)["messages"]
    assert "Your final answer must be in Yoruba" in first[0]["content"]
    assert "[English translation]\nGood morning, how are you?" in first[-1]["content"]


@respx.mock
def test_agent_reply_language_override(client):
    route = respx.post(CHAT_URL).mock(return_value=answer("Habari"))

    ask(client, message="Say hi", reply_language="sw")

    system = json.loads(route.calls.last.request.content)["messages"][0]["content"]
    assert "Your final answer must be in Swahili" in system


@respx.mock
def test_tool_errors_are_returned_to_the_model(client):
    respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call("translate", {"text": "Hi", "target_language": "klingon"}),
            answer("Sorry, I can't translate into that language."),
        ]
    )

    body = ask(client, message="Say hi in Klingon").json()

    assert "error" in body["steps"][0]["output"]
    assert body["answer"].startswith("Sorry")


@respx.mock
def test_unknown_tool_and_bad_arguments(client):
    respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call("delete_everything", {}),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "c2",
                                        "function": {"name": "translate", "arguments": "{not json"},
                                    }
                                ],
                            }
                        }
                    ]
                },
            ),
            answer("Done."),
        ]
    )

    steps = ask(client, message="hi").json()["steps"]

    assert steps[0]["output"] == {"error": "Unknown tool 'delete_everything'"}
    assert "error" in steps[1]["output"]


@respx.mock
def test_agent_step_limit_forces_final_answer(client, monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_STEPS", 2)
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call("list_languages", {}),
            tool_call("list_languages", {}, call_id="call_2"),
            answer("We support 14 languages."),
        ]
    )

    body = ask(client, message="Which languages?").json()

    assert body["answer"] == "We support 14 languages."
    assert len(body["steps"]) == 2
    final = json.loads(route.calls[2].request.content)
    assert "tools" not in final
    assert final["messages"][-1]["content"].startswith("Give your final answer now")


def test_agent_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setattr(config, "AGENT_PROVIDERS", [])

    assert ask(client, message="hi").status_code == 503


def test_agent_rejects_unsupported_reply_language(client):
    assert ask(client, message="hi", reply_language="tlh-Latn").status_code == 400


@pytest.mark.asyncio
async def test_time_tool():
    result = await agent.run_tool("get_current_time", {"timezone": "Africa/Nairobi"})
    assert result["timezone"] == "Africa/Nairobi"
    assert result["datetime"].endswith("+03:00")

    assert "error" in await agent.run_tool("get_current_time", '{"timezone": "Mars/Base"}')


@pytest.mark.asyncio
async def test_list_languages_tool():
    result = await agent.run_tool("list_languages", "{}")
    assert result["languages"]["pcm"] == "Nigerian Pidgin"


@respx.mock
def test_english_echo_is_stripped_from_translated_answer(client):
    respx.post(TRANSLATE_URL).mock(return_value=azure_translation("Abuja ni olú-ìlú Nàìjíríà."))
    respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call("translate", {"text": "The capital is Abuja.", "target_language": "yo"}),
            # The model repeats the English and re-types the hyphen as U+2011
            answer("The capital is Abuja.\n\nAbuja ni olú‑ìlú Nàìjíríà."),
        ]
    )
    respx.post(DETECT_URL).mock(return_value=httpx.Response(200, json=[{"language": "en"}]))

    body = ask(client, message="What is the capital?", reply_language="yo").json()

    assert body["answer"] == "Abuja ni olú-ìlú Nàìjíríà."


@respx.mock
def test_answer_is_translated_when_model_skips_the_tool(client):
    respx.post(DETECT_URL).mock(return_value=httpx.Response(200, json=[{"language": "en"}]))
    translate = respx.post(TRANSLATE_URL).mock(return_value=azure_translation("Asante"))
    respx.post(CHAT_URL).mock(return_value=answer("Thanks"))

    body = ask(client, message="Say thanks", reply_language="sw").json()

    assert body["answer"] == "Asante"
    assert translate.called


@respx.mock
def test_answer_already_in_reply_language_is_kept(client):
    respx.post(DETECT_URL).mock(return_value=httpx.Response(200, json=[{"language": "sw"}]))
    translate = respx.post(TRANSLATE_URL)
    respx.post(CHAT_URL).mock(return_value=answer("Asante sana"))

    body = ask(client, message="Say thanks", reply_language="sw").json()

    assert body["answer"] == "Asante sana"
    assert not translate.called


# --- Generation limits --------------------------------------------------------------


@respx.mock
def test_agent_model_calls_are_capped_with_max_tokens(client, monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_TOKENS", 333)
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call("list_languages", {}),
            answer("English and five African languages."),
        ]
    )

    response = ask(client, message="Which languages do you support?")

    assert response.status_code == 200
    # Every model call in the loop — including the one that runs a tool — is capped
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert len(bodies) == 2
    assert all(body["max_tokens"] == 333 for body in bodies)


@respx.mock
def test_agent_final_answer_call_is_capped_too(client, monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_STEPS", 1)
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            tool_call("list_languages", {}),
            answer("English and five African languages."),
        ]
    )

    response = ask(client, message="Which languages do you support?")

    assert response.status_code == 200
    # The tool call used the single step; the final tool-less answer is capped as well
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert len(bodies) == 2
    assert all(body["max_tokens"] == config.AGENT_MAX_TOKENS for body in bodies)
