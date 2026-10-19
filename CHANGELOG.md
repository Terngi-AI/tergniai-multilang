# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Prometheus metrics at `GET /metrics`: requests by route and status, latency, upstream
  calls per provider, translation cache hits/misses and rate-limited requests (#35).
- Retries with exponential backoff and jitter for transient upstream errors, honouring
  `Retry-After` (`UPSTREAM_MAX_RETRIES`, `UPSTREAM_RETRY_BASE_DELAY`,
  `UPSTREAM_RETRY_MAX_DELAY`) (#34).
- **Conversational chat** (`POST /v1/chat`) with server-side memory (`conversation_id`),
  `GET`/`DELETE /v1/chat/{id}`, and a web chat page at `/chat`. The assistant is now a general
  AI that chats about anything, not just translation.
- **96 languages**: 27 African plus European, Middle Eastern and Asian languages
  (Arabic, Chinese, Spanish, Polish, Dutch, Irish, Hindi, Japanese, …). Providers can be
  limited to certain languages (`<NAME>_LANGUAGES`); MORENA only handles its own 14.
- When every model is rate-limited, requests wait briefly (`RATE_LIMIT_MAX_WAIT_SECONDS`)
  instead of failing. Rate limits now cool down a key only for the model that hit them.
- Detected language codes are normalised (e.g. `zh` → `zh-Hans`, `no` → `nb`).
- **Multilingual agent** (`POST /v1/agent`): a tool-calling model that understands any
  supported language, uses `translate`, `detect_language`, `list_languages` and
  `get_current_time`, and answers in the user's (or a chosen) language. Answers are
  checked to be in the reply language. Configure with `AGENT_PROVIDERS` / `AGENT_MAX_STEPS`.
- All of MORENA's languages: French, Swahili, Kinyarwanda, Shona, isiZulu, isiXhosa,
  Setswana, Afrikaans and isiNdebele. Azure is skipped for languages it doesn't offer.
- `docs/USAGE.md` (curl, Python, JavaScript examples) and `docs/AGENT.md`.
- **Multiple providers, models and keys.** Any OpenAI-compatible API (Groq, OpenRouter,
  Together, Cerebras, Hugging Face, OpenAI, Ollama, or a custom URL) via `LLM_PROVIDERS`,
  `<NAME>_API_KEYS`, `<NAME>_MODELS` and `<NAME>_BASE_URL`. Keys rotate; rejected or
  rate-limited keys are put on cooldown; failing models and providers are skipped.
- Multiple Azure Translator keys (`AZURE_TRANSLATOR_KEYS`) with the same rotation and cooldown.
- **MORENA** (Vambo AI, Apache-2.0) provider: a free African-language model run locally with
  llama.cpp, plus `docker-compose.yml` and `docs/MORENA.md`.
- Per-task provider order: `CHAT_PROVIDERS`, `TRANSLATION_PROVIDERS`, `DETECTION_PROVIDERS`.
- LLM-based translation and language detection when Azure is unavailable.
- Nigerian Pidgin (`pcm`) as a supported language.
- `ENV_FILE` to choose which env file is loaded.

### Changed
- The `groq` SDK dependency was replaced by plain HTTP calls to OpenAI-compatible APIs.
- `GROQ_SYSTEM_PROMPT` is now `SYSTEM_PROMPT`.

### Fixed
- Translation results were cached in two places after #32 landed on top of #34/#35, so stale
  translations leaked between requests and 26 tests failed on `develop`. There is now one cache.
- Unhandled exceptions are counted as `500` in the request metrics.
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
