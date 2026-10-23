"""
WhatsApp bot routes: the webhook Meta calls, and sending messages
"""

import json
import secrets

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

import config
from models import WhatsAppSendRequest, WhatsAppSendResponse
from services import whatsapp
from services.languages import validate_language
from services.translator import translate_text

router = APIRouter()


def _require_configured() -> None:
    if not whatsapp.is_configured():
        raise HTTPException(status_code=503, detail="WhatsApp is not configured")


@router.get("/v1/whatsapp/webhook", include_in_schema=False)
async def verify_webhook(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta checks the webhook once, when it is set up"""
    _require_configured()
    if mode != "subscribe" or not secrets.compare_digest(token, config.WHATSAPP_VERIFY_TOKEN):
        raise HTTPException(status_code=403, detail="Verification failed")
    return PlainTextResponse(challenge)


@router.post("/v1/whatsapp/webhook", include_in_schema=False)
async def receive_webhook(request: Request, background: BackgroundTasks) -> dict:
    """Incoming messages. Meta gets an answer at once; replies are sent afterwards."""
    _require_configured()
    body = await request.body()
    if not whatsapp.valid_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON") from e
    for message in whatsapp.messages_in(payload if isinstance(payload, dict) else {}):
        background.add_task(whatsapp.handle, message)
    return {"status": "ok"}


@router.post("/v1/whatsapp/send", response_model=WhatsAppSendResponse)
async def send(request: WhatsAppSendRequest) -> WhatsAppSendResponse:
    """
    Send a WhatsApp message. Free text only reaches people who messaged you in the last 24
    hours; otherwise send an approved `template`. Only message people who agreed to it.
    """
    _require_configured()
    if (request.text is None) == (request.template is None):
        raise HTTPException(status_code=400, detail="Send either text or a template")
    try:
        to = whatsapp.normalise_phone(request.to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        if request.template is not None:
            ids = [
                await whatsapp.send_template(
                    to,
                    request.template.name,
                    request.template.language,
                    request.template.parameters,
                )
            ]
            return WhatsAppSendResponse(to=to, message_ids=ids)
        text = request.text or ""
        if request.to_language and request.to_language != request.from_language:
            validate_language(request.from_language, "Source")
            validate_language(request.to_language, "Target")
            text = await translate_text(text, request.from_language, request.to_language)
        return WhatsAppSendResponse(
            to=to, message_ids=await whatsapp.send_text(to, text), text=text
        )
    except whatsapp.WhatsAppError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
