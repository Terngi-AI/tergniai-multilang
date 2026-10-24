"""Locust load test for the Terngi API.

Start the mock upstream and the API first (see loadtest/README.md), then:

    locust -f loadtest/locustfile.py --host http://127.0.0.1:8766 \
        --headless -u 20 -r 5 -t 30s --only-summary

The tasks cover the paths called out in issue #44: health, translation cache hits and
misses, chat and the tool-using agent. Set LOADTEST_API_KEY when the API requires one.
"""

import os
import uuid

from locust import HttpUser, between, task

API_KEY = os.getenv("LOADTEST_API_KEY", "").strip()
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
HIT_TEXTS = [
    "Good morning",
    "Thank you",
    "How are you?",
    "Welcome to Terngi AI",
]


class TerngiUser(HttpUser):
    """A client that mixes cheap probes with translation and agent traffic."""

    wait_time = between(0.2, 0.8)

    def _post(self, path: str, payload: dict, name: str) -> None:
        with self.client.post(
            path, json=payload, headers=HEADERS, name=name, catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}: {response.text[:200]}")

    @task(2)
    def health(self) -> None:
        with self.client.get("/health", name="/health", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")

    @task(3)
    def translate_cache_miss(self) -> None:
        # Unique text makes the cache miss and exercises the upstream provider path.
        self._post(
            "/v1/translate",
            {
                "content": f"Load test sentence {uuid.uuid4().hex}",
                "from_language": "en",
                "to_language": "yo",
            },
            "/v1/translate (cache miss)",
        )

    @task(3)
    def translate_cache_hit(self) -> None:
        # A small, fixed set is warmed quickly and then served from the translation cache.
        text = HIT_TEXTS[uuid.uuid4().int % len(HIT_TEXTS)]
        self._post(
            "/v1/translate",
            {"content": text, "from_language": "en", "to_language": "yo"},
            "/v1/translate (cache hit)",
        )

    @task(1)
    def chat(self) -> None:
        self._post(
            "/v1/chat",
            {
                "message": "What is the capital of Nigeria?",
                "language": "en",
                "reply_language": "en",
            },
            "/v1/chat",
        )

    @task(1)
    def agent(self) -> None:
        self._post(
            "/v1/agent",
            {
                "message": "What is the capital of Nigeria?",
                "language": "en",
                "reply_language": "en",
            },
            "/v1/agent",
        )
