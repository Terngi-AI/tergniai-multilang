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
os.environ.setdefault("AZURE_TRANSLATOR_KEY", "test-azure-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
# Tests that hit upstream errors shouldn't really wait out the retry backoff
os.environ.setdefault("UPSTREAM_RETRY_BASE_DELAY", "0")

from main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Clear in-memory state between tests; use Azure only unless a test opts into fallback"""
    import config

    monkeypatch.setattr(config, "TRANSLATION_PROVIDER", "azure")
    from middleware import rate_limiter
    from services.translator import translation_cache

    translation_cache.clear()
    rate_limiter.reset()
    yield
    translation_cache.clear()
    rate_limiter.reset()
