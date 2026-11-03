"""
Translation feedback route
"""

import logging

from fastapi import APIRouter, HTTPException

from models import FeedbackRequest, FeedbackResponse
from services import feedback
from services.languages import validate_language

logger = logging.getLogger(__name__)

router = APIRouter(tags=["account"])


@router.post("/v1/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """
    Rate a translation or chat reply

    Feedback is only stored when `consent` is true. Records are append-only and never
    contain API keys. They may be published as part of the open evaluation set.
    """
    if not request.consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Feedback can only be stored with consent. Set consent to true after "
                "reading how feedback is used."
            ),
        )

    validate_language(request.from_language, "Source")
    validate_language(request.to_language, "Target")

    record = {
        "source_text": request.source_text,
        "translated_text": request.translated_text,
        "from_language": request.from_language,
        "to_language": request.to_language,
        "provider": request.provider,
        "rating": request.rating,
        "consent": True,
    }
    if request.correction:
        record["correction"] = request.correction

    try:
        await feedback.append(record)
    except feedback.FeedbackFull:
        logger.warning("Feedback storage is full; rejecting a new record")
        raise HTTPException(status_code=507, detail="Feedback storage is full") from None
    except feedback.FeedbackError:
        logger.exception("Feedback storage is unavailable")
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable") from None

    return FeedbackResponse()
