"""
Multilingual tool-using agent

The agent reasons in English with a tool-calling LLM (OpenAI-compatible providers) and uses
tools for translation and language detection. Translation goes through the normal provider
chain, so African-language output can come from MORENA, Azure or another LLM.
"""

import json
import logging
import unicodedata
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

import config
from services import llm, translator
from services.languages import resolve_source_language

logger = logging.getLogger(__name__)

# Receives streaming events: ("token" | "discard" | "tool", data)
OnEvent = Callable[[str, Dict[str, Any]], Awaitable[None]]

# Tool calls executed per model step; extra calls get an error result
MAX_TOOL_CALLS_PER_STEP = 8


def _language_list() -> str:
    return ", ".join(f"{code} ({name})" for code, name in config.SUPPORTED_LANGUAGES.items())


def tool_definitions() -> List[Dict[str, Any]]:
    """Tools offered to the model, in OpenAI function-calling format"""
    codes = list(config.SUPPORTED_LANGUAGES)
    return [
        {
            "type": "function",
            "function": {
                "name": "translate",
                "description": (
                    "Translate text into a supported language using specialised translation "
                    "models. Always use this to produce text in a language other than English "
                    "instead of translating yourself."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Text to translate"},
                        "target_language": {"type": "string", "enum": codes},
                        "source_language": {
                            "type": "string",
                            "enum": [*codes, "auto"],
                            "description": "Language of the text, or 'auto' to detect it",
                        },
                    },
                    "required": ["text", "target_language"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "detect_language",
                "description": "Identify the language of a piece of text.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_languages",
                "description": "List the languages Terngi AI supports, with their codes.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "Get the current date and time in a time zone.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timezone": {
                            "type": "string",
                            "description": "IANA time zone, e.g. Africa/Lagos (default)",
                        }
                    },
                },
            },
        },
    ]


# --- Tool implementations ---------------------------------------------------------


def _check_text(args: Dict[str, Any]) -> str:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("'text' must be a non-empty string")
    if len(text) > config.MAX_CONTENT_LENGTH:
        raise ValueError(f"'text' is longer than {config.MAX_CONTENT_LENGTH} characters")
    return text


async def _translate(args: Dict[str, Any]) -> Dict[str, Any]:
    text = _check_text(args)
    target = args.get("target_language")
    if target not in config.SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported target_language. Use one of: {_language_list()}")
    source = await resolve_source_language(text, args.get("source_language") or "auto")
    translation = await translator.translate_text(text, source, target)
    return {"translation": translation, "source_language": source, "target_language": target}


async def _detect_language(args: Dict[str, Any]) -> Dict[str, Any]:
    language, score = await translator.detect_language(_check_text(args))
    return {
        "language": language,
        "language_name": config.SUPPORTED_LANGUAGES.get(language),
        "score": score,
        "is_supported": language in config.SUPPORTED_LANGUAGES,
    }


async def _list_languages(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"languages": config.SUPPORTED_LANGUAGES}


async def _get_current_time(args: Dict[str, Any]) -> Dict[str, Any]:
    timezone = args.get("timezone") or "Africa/Lagos"
    try:
        now = datetime.now(ZoneInfo(str(timezone)))
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"Unknown time zone '{timezone}'") from e
    return {
        "timezone": timezone,
        "datetime": now.isoformat(timespec="seconds"),
        "weekday": now.strftime("%A"),
    }


TOOLS: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {
    "translate": _translate,
    "detect_language": _detect_language,
    "list_languages": _list_languages,
    "get_current_time": _get_current_time,
}


async def run_tool(name: str, raw_arguments: Any) -> Dict[str, Any]:
    """Execute a tool call; errors are returned to the model rather than raised"""
    if name not in TOOLS:
        return {"error": f"Unknown tool '{name}'"}
    try:
        if isinstance(raw_arguments, dict):
            args = raw_arguments
        else:
            args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        return await TOOLS[name](args)
    except (ValueError, TypeError) as e:
        return {"error": str(e)}
    except HTTPException as e:
        return {"error": str(e.detail)}


# --- Agent loop ---------------------------------------------------------------------


def _system_prompt(reply_language: str) -> str:
    reply_name = config.SUPPORTED_LANGUAGES[reply_language]
    if reply_language == "en":
        reply_rule = "Write your final answer in English."
    else:
        reply_rule = (
            f"Your final answer must be in {reply_name}. Write it in English first, then call "
            f"`translate` with target_language='{reply_language}', and reply with exactly the "
            "translated text. Do not translate it yourself."
        )
    return (
        "You are Terngi AI, a friendly, knowledgeable and culturally aware AI assistant made "
        "for African users. If asked who you are, say you are Terngi AI.\n\n"
        "Chat naturally about anything, like any general AI assistant: answer questions, "
        "explain ideas, give practical advice, help with writing, studies, work, business, "
        "health information, farming, coding and everyday life. Remember what the user said "
        "earlier in the conversation and build on it. Ask a short clarifying question when a "
        "request is ambiguous. Be warm and direct, and match the length of your answer to the "
        "question: brief for small talk, detailed when asked to explain.\n\n"
        f"You understand these languages: {_language_list()}. Messages in other languages "
        "arrive with an English translation to help you.\n\n"
        "Tools are optional helpers, not the point of the conversation. Use `translate` "
        "whenever you need text in a non-English language (for example when the user asks how "
        "to say something), `detect_language` if unsure of a language, and `get_current_time` "
        "for dates and times. Never invent tool results and don't mention tools to the user.\n\n"
        f"{reply_rule}"
    )


def _parse_step(message: Dict[str, Any]) -> Dict[str, Any]:
    """Accept a model step only if it has tool calls or a non-empty answer"""
    tool_calls = message.get("tool_calls") or []
    content = (message.get("content") or "").strip()
    if not tool_calls and not content:
        raise ValueError("empty step")
    return {"content": content, "tool_calls": tool_calls}


def _normalise(text: str) -> str:
    """Normalise Unicode and look-alike punctuation so model echoes can be compared"""
    text = unicodedata.normalize("NFC", text)
    for char in ("\u2010", "\u2011", "\u2012", "\u2013"):
        text = text.replace(char, "-")
    return " ".join(text.replace("\u00a0", " ").split())


async def _finalise_answer(answer: str, reply_language: str, steps: List[Dict[str, Any]]) -> str:
    """
    Make sure the answer is in the reply language. Models sometimes echo the English draft
    next to the translation, or skip the translate tool entirely.
    """
    if reply_language == "en":
        return answer

    translations = [
        step["output"]["translation"]
        for step in steps
        if step["tool"] == "translate"
        and step["output"].get("target_language") == reply_language
        and "translation" in step["output"]
    ]
    if translations:
        last = translations[-1]
        return last if _normalise(last) in _normalise(answer) else answer

    # The model never translated: do it here (auto-detect in case it already did so itself)
    source = await resolve_source_language(answer, "auto")
    return await translator.translate_text(answer, source, reply_language)


async def run_agent(
    message: str,
    language: str = "auto",
    reply_language: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    on_event: Optional[OnEvent] = None,
    context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the agent on a user message

    Args:
        message: The user's message, in any supported language
        language: Language of the message, or "auto" to detect it
        reply_language: Language for the answer (defaults to the message's language)
        history: Previous user/assistant turns
        on_event: If given, the answer is streamed. Receives ("token", {"text"}) as text
            arrives, ("discard", {}) when streamed text turns out to precede tool calls and
            should be dropped, and ("tool", {"tool", "ok"}) for each tool that runs
        context: Facts from the operator to answer from (e.g. a business's opening hours)

    Returns:
        Dict with the answer, the languages used and the tool steps taken
    """
    if not llm.is_configured(config.AGENT_PROVIDERS, kind="openai"):
        raise HTTPException(status_code=503, detail="Agent is not configured")

    source = await resolve_source_language(message, language)
    reply = reply_language or source

    # Give the model the original message plus an English rendering of it
    user_content = message
    if source != "en":
        english = await translator.translate_text(message, source, "en")
        user_content = (
            f"[Message in {config.SUPPORTED_LANGUAGES[source]}]\n{message}\n\n"
            f"[English translation]\n{english}"
        )

    system = _system_prompt(reply)
    if context:
        system += (
            f"\n\nInformation from the operator of this service, to use when relevant:\n{context}"
        )
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in history or []:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_content})

    steps: List[Dict[str, Any]] = []
    tools = tool_definitions()

    for _ in range(config.AGENT_MAX_STEPS):
        streamed = False

        async def on_token(text: str) -> None:
            nonlocal streamed
            streamed = True
            if on_event is not None:
                await on_event("token", {"text": text})

        step = await llm.complete_message(
            config.AGENT_PROVIDERS,
            messages,
            parse=_parse_step,
            tools=tools,
            temperature=0.3,
            on_token=on_token if on_event is not None else None,
        )
        if step["tool_calls"] and streamed and on_event is not None:
            await on_event("discard", {})
        if not step["tool_calls"]:
            return {
                "answer": await _finalise_answer(step["content"], reply, steps),
                "language": source,
                "reply_language": reply,
                "steps": steps,
            }

        messages.append(
            {
                "role": "assistant",
                "content": step["content"] or None,
                "tool_calls": step["tool_calls"],
            }
        )
        for index, call in enumerate(step["tool_calls"]):
            function = call.get("function") or {}
            name = str(function.get("name", ""))
            raw_arguments = function.get("arguments", "{}")
            if index < MAX_TOOL_CALLS_PER_STEP:
                output = await run_tool(name, raw_arguments)
            else:
                output = {"error": "Too many tool calls in one step"}
            try:
                arguments = (
                    json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                )
            except ValueError:
                arguments = raw_arguments
            steps.append({"tool": name, "arguments": arguments, "output": output})
            logger.info("Agent tool %s -> %s", name, "error" if "error" in output else "ok")
            if on_event is not None:
                await on_event("tool", {"tool": name, "ok": "error" not in output})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": json.dumps(output, ensure_ascii=False),
                }
            )

    # Out of steps: ask for a final answer without tools
    messages.append({"role": "user", "content": "Give your final answer now, without using tools."})
    answer = await llm.complete(
        config.AGENT_PROVIDERS,
        messages,
        parse=lambda text: _parse_step({"content": text})["content"],
    )
    return {
        "answer": await _finalise_answer(answer, reply, steps),
        "language": source,
        "reply_language": reply,
        "steps": steps,
    }
