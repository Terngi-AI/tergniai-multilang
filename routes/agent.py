"""
Agent route for the Terngi Translation API
"""

import logging

from fastapi import APIRouter, HTTPException

from models import AgentRequest, AgentResponse
from services.agent import run_agent
from services.languages import validate_language

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v1/agent", response_model=AgentResponse)
async def agent(request: AgentRequest):
    """
    Ask the multilingual agent. It understands any supported language, uses tools
    (translation, language detection, time) and answers in the reply language.
    """
    if request.reply_language is not None:
        validate_language(request.reply_language, "Reply")

    try:
        result = await run_agent(
            request.message,
            language=request.language,
            reply_language=request.reply_language,
            history=[turn.model_dump() for turn in request.history or []],
        )
        return AgentResponse(**result)

    except HTTPException as e:
        raise e  # Re-raise HTTPExceptions
    except Exception as e:
        logger.exception("Unexpected agent error")
        raise HTTPException(status_code=500, detail="Agent error") from e
