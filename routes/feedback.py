"""
Translation feedback route
"""

import logging

from fastapi import APIRouter, HTTPException, Request

import config
from middleware import authenticated_key, rate_limit_id
from models import FeedbackRequest, FeedbackResponse
from services import feedback, usage
from services.languages import validate_language

logger = logging.getLogger(__name__)

router = APIRouter(tags=["account"])


@router.post("/v1/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest, http_request: Request):
    """
    Rate a translation or chat reply

    Feedback is only stored when `consent` is true. Records are append-only and never
    contain API keys. They may be published as part of the open evaluation set.

    Each API key may store `FEEDBACK_PER_KEY_PER_DAY` records per UTC day (`429` with
    `Retry-After` beyond that). Sending the same rating of the same translation again on the
    same day stores nothing and returns `{"status": "duplicate"}`.
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

    caller = rate_limit_id(http_request)
    admission = await feedback.admit(caller, record)
    if admission is feedback.Admission.DUPLICATE:
        return FeedbackResponse(status="duplicate")
    if admission is feedback.Admission.LIMITED:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily feedback limit reached ({config.FEEDBACK_PER_KEY_PER_DAY} records per "
                "API key). Please try again tomorrow."
            ),
            headers={"Retry-After": str(usage.seconds_until_tomorrow())},
        )
    # Only key holders get a label; an IP-derived label would be personal data
    if authenticated_key(http_request):
        record["submitter"] = feedback.submitter_label(caller)

    try:
        await feedback.append(record)
    except feedback.FeedbackFull:
        await feedback.release(caller, record)
        logger.warning("Feedback storage is full; rejecting a new record")
        raise HTTPException(status_code=507, detail="Feedback storage is full") from None
    except feedback.FeedbackError:
        await feedback.release(caller, record)
        logger.exception("Feedback storage is unavailable")
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable") from None

    return FeedbackResponse()
