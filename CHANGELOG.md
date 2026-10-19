# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Groq LLM translation and language detection, with automatic fallback when Azure Translator
  is not configured or fails. `TRANSLATION_PROVIDER` selects `auto`, `azure` or `groq`.

### Fixed
- Translation endpoints no longer fail entirely when the Azure key is missing or invalid.
- The assistant identifies itself as Terngi AI instead of the underlying model.

## [1.0.0] - 2026-10-19

### Security
- Removed hardcoded Azure and Groq API keys; configuration now comes from environment variables.
- Upstream error details are logged instead of returned to clients.
- `memory_context` only accepts `user` / `assistant` roles (blocks system-prompt injection).
- Docker image runs as a non-root user; `--reload` removed from production.

### Added
- `POST /v1/detect` language detection and `"auto"` source language on translate/converse.
- `POST /v1/translate/batch` for translating up to 25 texts in one request.
- In-memory TTL/LRU translation cache.
- Optional client API-key authentication (`API_KEYS`, `X-API-Key` header).
- Per-client rate limiting with `X-RateLimit-*` and `Retry-After` headers.
- `X-Request-ID` / `X-Process-Time-Ms` headers and structured request logs.
- `/health/ready` readiness probe.
- MIT license, contributing guide, code of conduct, security policy, issue/PR templates.
- CI: lint, mypy, tests on Python 3.10–3.13, Docker smoke test, gitleaks, pip-audit, Dependabot.
- `/health` endpoint and Docker `HEALTHCHECK`.
- Test suite with mocked upstream services.
- Request size limits and optional CORS.

### Changed
- Default Groq model is now `openai/gpt-oss-120b` (`llama-3.3-70b-versatile` was retired by Groq).
- Azure and Groq calls are now async with timeouts (no longer block the event loop).
- Upstream failures return `502`, missing configuration returns `503`.
- Pinned dependency versions; removed the invalid `typing` requirement.
- Staging deploy workflow runs CI first, skips on forks, injects secrets as env vars and tags images by commit SHA.

### Removed
- Production deploy workflow (production deploys are not run from the open-source repo).
