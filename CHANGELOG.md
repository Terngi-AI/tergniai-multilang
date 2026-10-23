# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **WhatsApp bot** (`/v1/whatsapp/webhook`): people message your WhatsApp number in any
  supported language and get answers in that language from the agent, with memory (in
  memory or Redis). Commands: `LANGUAGE`, `RESET`, `HELP`. Webhooks are verified by Meta's
  signature, repeated deliveries are answered once, phone numbers are stored as hashes.
  `WHATSAPP_CONTEXT` gives the bot facts to answer from. See `docs/WHATSAPP.md`
- `POST /v1/whatsapp/send`: send text (optionally translated) or an approved template
- The agent accepts an optional `context` with facts from the operator

### Security
- `certifi` upgraded to 2026.10.19 (PYSEC-2026-4320).
- **Security workflow** on every PR and daily: ClamAV malware scan, Semgrep static analysis,
  pip-audit + OSV-Scanner dependency audits, Trivy image/Dockerfile scan, and an OWASP ZAP attack
  simulation against the running API. OpenSSF Scorecard runs weekly.
- Fixed a rate-limit bypass: made-up `X-API-Key` values each got their own limit (and memory).
  Only valid keys now count as a separate client, and idle clients are forgotten.
- Request bodies over `MAX_REQUEST_BYTES` (1 MiB) are rejected with `413`, including streamed ones.
- Security headers (CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, HSTS over HTTPS).
- All GitHub Actions pinned to commit SHAs, checkout no longer keeps the token, scanner versions pinned.
- Hash-locked dependencies (`requirements.lock`, `requirements-dev.lock`) installed with
  `--require-hashes`. This also upgrades indirect dependencies with known vulnerabilities
  (anyio 4.15.1, idna 3.20, pygments 2.21.0).

### Removed
- Dependabot. Dependency vulnerabilities are caught by the daily security scan instead.

### Added
- **Streaming chat** (#10): `POST /v1/chat/stream` sends the reply as Server-Sent Events
  (`start`, `token`, `discard`, `tool`, `done`, `error`) while it's generated; the web chat now
  shows replies word by word and which tool is running. Fallback to another model still works
  until the first token.
- **Redis backend** (#11): set `REDIS_URL` to share the translation cache, rate limits and chat
  conversations between replicas and keep conversations across restarts. Falls back to
  in-memory state when unset. If Redis is down, translation works without the cache and the
  rate limiter fails open; chat returns `503`. `/health/ready` reports `storage`.
  `docker compose up` now starts Redis too.
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
- A provider whose server can't be reached (e.g. MORENA switched off) is skipped for
  `PROVIDER_DOWN_COOLDOWN_SECONDS` (30s) instead of being retried on every request.
- Single texts are translated as plain text instead of strict JSON, which some providers
  rejected for long outputs (`Failed to validate JSON`), wasting several seconds per request.
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
