"""
WhatsApp bot (WhatsApp Cloud API by Meta)

People message your WhatsApp number in any supported language and Terngi AI answers in that
language, remembering the conversation. Commands: LANGUAGE <name or code>, RESET, HELP.

Webhooks are only accepted with a valid signature from Meta. Phone numbers are stored only
as hashes, and memory expires after WHATSAPP_MEMORY_TTL_SECONDS.
"""

import hashlib
import hmac
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

import config
from services import conversations, deadline, identifiers
from services.agent import run_agent
from services.retry import RETRY_STATUS_CODES, retry_delay
from services.store import StoreError, make_store
from services.text import normalize_text
from services.translator import translate_text

logger = logging.getLogger(__name__)

MAX_TEXT = 4096  # WhatsApp's limit for one text message
COMMANDS = ("LANGUAGE", "RESET", "HELP")
HELP = (
    "Ask me anything and I'll answer in your language.\n"
    "LANGUAGE <name or code>: change language (e.g. LANGUAGE Yoruba)\n"
    "RESET: start a new conversation"
)

# Per person (keyed by a hash of their number): their language and conversation
_users = make_store("whatsapp-user", config.WHATSAPP_MAX_USERS, config.WHATSAPP_MEMORY_TTL_SECONDS)
# Message ids already handled: Meta retries a webhook if it doesn't get a quick reply
_seen = make_store("whatsapp-seen", config.WHATSAPP_MAX_USERS, 24 * 3600)


class WhatsAppError(Exception):
    """Sending failed; the message is safe to show"""


def is_configured() -> bool:
    return all(
        (
            config.WHATSAPP_PHONE_NUMBER_ID,
            config.WHATSAPP_ACCESS_TOKEN,
            config.WHATSAPP_APP_SECRET,
            config.WHATSAPP_VERIFY_TOKEN,
        )
    )


def valid_signature(body: bytes, header: Optional[str]) -> bool:
    """Meta signs each webhook with the app secret (X-Hub-Signature-256: sha256=<hex>)"""
    if not config.WHATSAPP_APP_SECRET or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(config.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256=") :], expected)


def messages_in(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Incoming messages in a webhook payload (delivery statuses are ignored)"""
    found: List[Dict[str, Any]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            found.extend((change.get("value") or {}).get("messages") or [])
    return found


def normalise_phone(phone: str) -> str:
    """Digits only, with the country code: '+44 7700 900123' -> '447700900123'"""
    digits = re.sub(r"\D", "", phone)
    if not 7 <= len(digits) <= 15:
        raise ValueError("Use a phone number with its country code, e.g. +447700900123")
    return digits


def split(text: str, limit: int = MAX_TEXT) -> List[str]:
    """Split long text into WhatsApp-sized messages, at line or word breaks if possible"""
    parts: List[str] = []
    while len(text) > limit:
        cut = max(text.rfind("\n", 0, limit), text.rfind(" ", 0, limit))
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return parts + ([text] if text else [])


def find_language(text: str) -> Optional[str]:
    """A supported language code from a code or name: 'yo', 'Yoruba', 'pidgin'"""
    wanted = text.strip().lower()
    if wanted in config.SUPPORTED_LANGUAGES:
        return wanted
    for code, name in config.SUPPORTED_LANGUAGES.items():
        if name.lower() == wanted or (len(wanted) >= 4 and wanted in name.lower()):
            return code
    return None


# --- Sending ---------------------------------------------------------------------------


async def _post(payload: Dict[str, Any]) -> str:
    """Send one message, retrying throttling and transient errors; returns its id"""
    url = f"{config.WHATSAPP_GRAPH_URL}/{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}"}
    body = {"messaging_product": "whatsapp", **payload}
    async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT) as client:
        for attempt in range(config.UPSTREAM_MAX_RETRIES + 1):
            deadline.consume_attempt()
            try:
                response = await client.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=deadline.timeout(config.REQUEST_TIMEOUT),
                )
            except httpx.HTTPError as e:
                raise WhatsAppError(f"Can't reach WhatsApp: {type(e).__name__}") from e
            if response.status_code not in RETRY_STATUS_CODES:
                break
            delay = retry_delay(attempt, response)
            if delay is None or attempt == config.UPSTREAM_MAX_RETRIES:
                break
            await deadline.sleep(delay)
    if response.status_code != 200:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        raise WhatsAppError(
            f"WhatsApp rejected the message ({response.status_code}) {detail}".strip()
        )
    return str((response.json().get("messages") or [{}])[0].get("id", ""))


async def send_text(to: str, text: str) -> List[str]:
    """Send text, split if long. Only works within 24 hours of the person's last message."""
    text = normalize_text(text)
    return [
        await _post({"to": to, "type": "text", "text": {"body": part, "preview_url": False}})
        for part in split(text)
    ]


async def send_template(to: str, name: str, language_code: str, parameters: List[str]) -> str:
    """Send an approved template: needed to start a conversation or after 24 hours"""
    template: Dict[str, Any] = {"name": name, "language": {"code": language_code}}
    if parameters:
        template["components"] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": normalize_text(parameter)} for parameter in parameters
                ],
            }
        ]
    return await _post({"to": to, "type": "template", "template": template})


# --- The bot ---------------------------------------------------------------------------


def _key(phone: str) -> str:
    # Keyed (HMAC-SHA256) so a leaked store cannot be turned back into phone numbers
    return identifiers.keyed_hash(phone)


async def _say(text: str, language: Optional[str]) -> str:
    """
    A fixed bot message in the person's language. Command words stay in English, because
    that's what the bot understands; if a translation loses one, the English is added.
    """
    if not language or language == "en":
        return text
    marks = {word: f"[[{chr(65 + n)}]]" for n, word in enumerate(COMMANDS)}  # [[A]], [[B]]...
    protected = text
    for word, mark in marks.items():
        protected = re.sub(rf"\b{word}\b", mark, protected)
    try:
        translated = await translate_text(protected, "en", language)
    except HTTPException:
        return text
    for word, mark in marks.items():
        if mark in protected and mark not in translated:
            return f"{translated}\n({text})"
        translated = translated.replace(mark, word)
    return translated


async def _first_time(message_id: str) -> bool:
    """True the first time a message id is seen"""
    if not message_id:
        return True
    if await _seen.get(message_id):
        return False
    await _seen.set(message_id, True)
    return True


async def reply_to(message: Dict[str, Any]) -> Optional[str]:
    """The bot's reply to one incoming message, or None if it was already handled"""
    if not await _first_time(str(message.get("id", ""))):
        return None
    phone = str(message.get("from", ""))
    key = _key(phone)
    user = await _users.get(key) or {"language": None, "conversation_id": None}
    language = user["language"]
    text = normalize_text(((message.get("text") or {}).get("body") or "").strip())

    if message.get("type") != "text" or not text:
        return await _say("Sorry, I can only read text messages for now.", language)

    words = text.split(maxsplit=1)
    command = words[0].upper().strip(".!")
    if command == "HELP":
        return await _say(HELP, language)
    if command == "RESET":
        await _users.set(key, {**user, "conversation_id": None})
        return await _say("Done: let's start a new conversation.", language)
    if command in ("LANGUAGE", "LANG"):
        code = find_language(words[1]) if len(words) > 1 else None
        if not code:
            return await _say("Which language? For example: LANGUAGE Yoruba, LANGUAGE ha", language)
        await _users.set(key, {**user, "language": code})
        return await _say(f"Your language is now {config.SUPPORTED_LANGUAGES[code]}.", code)

    owner = f"whatsapp:{key}"
    conversation_id = user["conversation_id"]
    history = await conversations.get(conversation_id, owner) if conversation_id else None
    if history is None:
        conversation_id, history = await conversations.create(owner), []
    try:
        result = await run_agent(
            text,
            language=language or "auto",
            reply_language=language,
            history=history,
            context=config.WHATSAPP_CONTEXT or None,
        )
    except (HTTPException, StoreError):
        logger.exception("WhatsApp bot could not answer")
        return await _say("Sorry, I couldn't answer just now. Please try again later.", language)
    await conversations.append(
        conversation_id,
        owner,
        {"role": "user", "content": text},
        {"role": "assistant", "content": result["answer"]},
    )
    answer = str(result["answer"])
    if language is None:  # first message: remember the language they wrote in
        language = str(result["language"])
        if config.WHATSAPP_WELCOME:
            answer = f"{await _say(config.WHATSAPP_WELCOME, language)}\n\n{answer}"
    await _users.set(key, {"language": language, "conversation_id": conversation_id})
    return answer


async def handle(message: Dict[str, Any]) -> None:
    """Answer one incoming message (runs after the webhook has returned)"""
    # Background tasks run inside the webhook's ASGI call. Give this delivery its own
    # budget so it is neither cut off nor judged against the time Meta's request took.
    tokens = deadline.begin(config.REQUEST_DEADLINE_SECONDS)
    try:
        answer = await reply_to(message)
        if answer:
            await send_text(str(message.get("from", "")), answer)
    except (WhatsAppError, StoreError, HTTPException) as e:
        logger.warning("WhatsApp reply failed: %s", e)
    finally:
        deadline.end(tokens)


def clear() -> None:
    """Forget everyone (tests)"""
    _users.clear()
    _seen.clear()
