"""
Tests that upstream error bodies (which can echo user text) never reach the logs
at INFO/WARNING, and that upstream errors are correlated with the request ID
"""

import logging

import httpx
import respx

import config
from services.retry import error_summary
from tests.conftest import GROQ_URL

CHAT_URL = GROQ_URL + "/chat/completions"
TRANSLATE_URL = config.AZURE_TRANSLATOR_ENDPOINT + "/translate"

SECRET = "user-secret-do-not-log-42"
REQUEST_ID = "req-test-89"


def logged_at_and_above(caplog, level: int) -> str:
    """Everything logged at `level` or above, as a single string"""
    return "\n".join(r.getMessage() for r in caplog.records if r.levelno >= level)


# --- error_summary ------------------------------------------------------------------


def test_error_summary_reads_the_nested_openai_style_code():
    response = httpx.Response(
        400,
        json={"error": {"message": "bad", "type": "invalid_request_error", "code": "bad_code"}},
    )

    assert error_summary(response) == "code=bad_code"


def test_error_summary_falls_back_to_the_type():
    response = httpx.Response(
        400, json={"error": {"message": "bad", "type": "invalid_request_error"}}
    )

    assert error_summary(response) == "code=invalid_request_error"


def test_error_summary_reads_a_top_level_azure_style_code():
    response = httpx.Response(400, json={"code": "BadRequest", "message": "bad"})

    assert error_summary(response) == "code=BadRequest"


def test_error_summary_handles_non_json_and_codeless_bodies():
    assert error_summary(httpx.Response(400, text="<html>gateway error</html>")) == (
        "non-JSON body"
    )
    assert error_summary(httpx.Response(400, json={"message": "bad"})) == "no error code"
    assert error_summary(httpx.Response(400, json={"error": "plain string"})) == "no error code"


def test_error_summary_truncates_long_codes():
    response = httpx.Response(400, json={"error": {"code": "x" * 200, "message": "bad"}})

    assert error_summary(response) == "code=" + "x" * 64


# --- LLM provider errors ------------------------------------------------------------


@respx.mock
def test_llm_error_body_never_reaches_info_or_warning(client, caplog):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": {
                    "message": f"Content rejected: {SECRET} violates the policy",
                    "type": "invalid_request_error",
                    "code": "content_filter",
                }
            },
        )
    )

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/v1/agent",
            json={"message": SECRET, "language": "en"},
            headers={"X-Request-ID": REQUEST_ID},
        )

    assert response.status_code == 502
    logged = logged_at_and_above(caplog, logging.INFO)
    # The user text echoed in the provider's error message never reaches the logs...
    assert SECRET not in logged
    # ...but the provider's error code and the request ID are kept for correlation
    assert "code=content_filter" in logged
    assert REQUEST_ID in logged


@respx.mock
def test_llm_error_body_is_available_at_debug(client, caplog):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"message": f"rejected: {SECRET}", "code": "content_filter"}}
        )
    )

    with caplog.at_level(logging.DEBUG, logger="services.llm"):
        client.post(
            "/v1/agent",
            json={"message": SECRET, "language": "en"},
            headers={"X-Request-ID": REQUEST_ID},
        )

    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    # At DEBUG the (truncated) body is available for debugging
    assert any(SECRET in message for message in debug_messages)
    # ...but it stays out of everything at INFO and above
    assert SECRET not in logged_at_and_above(caplog, logging.INFO)


# --- Azure Translator errors ----------------------------------------------------------


@respx.mock
def test_azure_error_body_never_reaches_info_or_error(client, caplog):
    respx.post(TRANSLATE_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": {"code": "BadRequest", "message": f"Text '{SECRET}' is invalid"}},
        )
    )

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/v1/translate",
            json={"content": SECRET, "from_language": "en", "to_language": "yo"},
            headers={"X-Request-ID": REQUEST_ID},
        )

    assert response.status_code == 502
    logged = logged_at_and_above(caplog, logging.INFO)
    assert SECRET not in logged
    assert "code=BadRequest" in logged
    assert REQUEST_ID in logged
