"""
Shared test fixtures
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make the project root importable and provide dummy credentials
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Tests that hit upstream errors shouldn't really wait out the retry backoff
os.environ.setdefault("UPSTREAM_RETRY_BASE_DELAY", "0")
# Never read a developer's local .env during tests
os.environ["ENV_FILE"] = os.devnull
os.environ.setdefault("AZURE_TRANSLATOR_KEY", "test-azure-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


GROQ_URL = "https://api.groq.com/openai/v1"


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """
    Give every test the same configuration, independent of any local .env:
    Azure with one key, and one Groq provider with one key and one model.
    Translation and detection use Azure only unless a test opts into the LLM chain.
    """
    import config
    from middleware import rate_limiter
    from services import conversations, whatsapp
    from services.keypool import key_pool
    from services.translator import translation_cache

    monkeypatch.setattr(config, "AZURE_TRANSLATOR_KEYS", ["test-azure-key"])
    monkeypatch.setattr(
        config,
        "LLM_PROVIDERS",
        {
            "groq": config.LLMProvider(
                name="groq",
                kind="openai",
                base_url=GROQ_URL,
                api_keys=("test-groq-key",),
                models=("model-a",),
            )
        },
    )
    monkeypatch.setattr(config, "CHAT_PROVIDERS", ["groq"])
    monkeypatch.setattr(config, "AGENT_PROVIDERS", ["groq"])
    # Tests never sleep waiting for rate limits unless they opt in
    monkeypatch.setattr(config, "RATE_LIMIT_MAX_WAIT_SECONDS", 0)
    monkeypatch.setattr(config, "TRANSLATION_PROVIDERS", ["azure"])
    monkeypatch.setattr(config, "DETECTION_PROVIDERS", ["azure"])

    translation_cache.clear()
    rate_limiter.reset()
    key_pool.reset()
    conversations.clear()
    whatsapp.clear()
    yield
    translation_cache.clear()
    rate_limiter.reset()
    key_pool.reset()
    conversations.clear()
    whatsapp.clear()
