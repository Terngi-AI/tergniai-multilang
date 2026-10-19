# Terngi AI — Translation & Conversation API

[![CI](https://github.com/Terngi-AI/tergniai-multilang/actions/workflows/ci.yml/badge.svg)](https://github.com/Terngi-AI/tergniai-multilang/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Good first issues](https://img.shields.io/github/issues/Terngi-AI/tergniai-multilang/good%20first%20issue?label=good%20first%20issues&color=7057ff)](https://github.com/Terngi-AI/tergniai-multilang/labels/good%20first%20issue)
[![GitHub stars](https://img.shields.io/github/stars/Terngi-AI/tergniai-multilang?style=social)](https://github.com/Terngi-AI/tergniai-multilang/stargazers)

**Open-source translation and AI conversation for Nigerian languages.**

A FastAPI service that translates between **English, Yoruba, Hausa and Igbo** and holds
multilingual conversations with an LLM. Translation is powered by
[Azure Translator](https://learn.microsoft.com/azure/ai-services/translator/) and responses
by [Groq](https://groq.com/) (`openai/gpt-oss-120b` by default).

## Why this project?

More than 100 million people speak Yoruba, Hausa or Igbo, yet these languages are still
poorly served by most software. Terngi AI gives developers a simple, self-hostable API to
build apps, chatbots and services that speak to people in their own language, and it is
built in the open so native speakers and developers can improve it together.

⭐ **If this is useful to you, star the repo** — it helps more people find it.

## Features

- **Translate** text between any two supported languages, one at a time or in batches
- **Auto-detect** the source language — pass `"from_language": "auto"` to any endpoint
- **Converse** in any supported language; the reply comes back in the target language,
  with optional multi-turn memory (`memory_context`)
- **Translation cache** (in-memory TTL/LRU) to save Azure quota on repeated phrases
- **API-key authentication** (`X-API-Key`) and **per-client rate limiting**
- **Request IDs** (`X-Request-ID`) and timing headers for tracing
- Input validation, upstream timeouts and consistent JSON error responses
- Liveness (`/health`) and readiness (`/health/ready`) probes
- Docker image with a health check, running as a non-root user

## Quick start

### Prerequisites

- Python 3.10+
- A Groq API key (an Azure Translator key is optional)

### Run locally

```bash
git clone https://github.com/Terngi-AI/tergniai-multilang.git
cd tergniai-multilang
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env   # then fill in your keys
uvicorn main:app --reload
```

Open http://localhost:8000/docs for the interactive API docs.

### Run with Docker

```bash
docker build -t terngi-ai .
docker run --rm -p 8000:8000 --env-file .env terngi-ai
```

## Configuration

All configuration comes from environment variables (see [`.env.example`](.env.example)).

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_TRANSLATOR_KEY` | no* | — | Azure Translator subscription key |
| `AZURE_TRANSLATOR_ENDPOINT` | no | `https://api.cognitive.microsofttranslator.com` | Translator endpoint |
| `AZURE_TRANSLATOR_LOCATION` | no | `global` | Azure resource region |
| `GROQ_API_KEY` | yes* | — | Groq API key (chat, and translation fallback) |
| `TRANSLATION_PROVIDER` | no | `auto` | `auto` (Azure, falling back to Groq), `azure` or `groq` |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` | Groq model ID |
| `REQUEST_TIMEOUT` | no | `30` | Upstream timeout in seconds |
| `UPSTREAM_MAX_RETRIES` | no | `2` | Retries for upstream `429`/`5xx`/connection errors (Azure and Groq); `0` disables |
| `UPSTREAM_RETRY_BASE_DELAY` | no | `0.5` | First backoff step in seconds; doubles each retry, with full jitter (Azure) |
| `UPSTREAM_RETRY_MAX_DELAY` | no | `10` | Longest wait between retries; a longer `Retry-After` fails fast (Azure) |
| `MAX_CONTENT_LENGTH` | no | `5000` | Max characters per message |
| `MAX_MEMORY_MESSAGES` | no | `20` | Max turns in `memory_context` |
| `API_KEYS` | no | *(auth disabled)* | Comma-separated client keys accepted in `X-API-Key` |
| `RATE_LIMIT_PER_MINUTE` | no | `60` | Requests per minute per client; `0` disables |
| `CACHE_TTL_SECONDS` | no | `3600` | Translation cache lifetime; `0` disables |
| `CACHE_MAX_ITEMS` | no | `1000` | Max cached translations |
| `MAX_BATCH_SIZE` | no | `25` | Max texts per batch request |
| `MAX_BATCH_CHARACTERS` | no | `50000` | Max total characters per batch |
| `CORS_ORIGINS` | no | *(disabled)* | Comma-separated allowed origins |
| `LOG_LEVEL` | no | `INFO` | Python log level |

\* You need at least one translation provider. With only `GROQ_API_KEY`, the LLM handles
translation and language detection too. With both keys, Azure is used first and Groq takes
over automatically if Azure fails. The app starts without keys; endpoints that need a missing
key return `503`.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | API info and supported languages |
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (are upstream keys configured?) |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/v1/languages` | Supported language codes |
| `POST` | `/v1/translate` | Translate text |
| `POST` | `/v1/translate/batch` | Translate up to 25 texts in one request |
| `POST` | `/v1/detect` | Detect the language of a text |
| `POST` | `/v1/converse` | Translate and get an LLM reply |

### Authentication & rate limits

When `API_KEYS` is set, every `/v1/*` endpoint except `/v1/languages` requires an
`X-API-Key` header. Each client (API key, or IP address when no key is sent) may make
`RATE_LIMIT_PER_MINUTE` requests per minute. Responses include `X-RateLimit-Limit` and
`X-RateLimit-Remaining`; when exceeded you get `429` with a `Retry-After` header.

> The cache and rate limiter are in-memory, so each server process keeps its own state.
> Run behind a shared limiter (e.g. your API gateway) if you scale out to many replicas.

### Metrics

`GET /metrics` serves Prometheus metrics. Like the health checks, it needs no API key
and isn't rate limited, so keep it off the public internet (for example, only expose it on
your internal network or block it at the reverse proxy).

| Metric | Labels | Description |
|---|---|---|
| `terngi_http_requests_total` | `method`, `route`, `status` | Requests handled, including `401`/`429` rejections |
| `terngi_http_request_duration_seconds` | `method`, `route` | Request latency histogram |
| `terngi_upstream_requests_total` | `service` (`azure`/`groq`), `outcome` (`success`/`error`) | Upstream calls |
| `terngi_upstream_request_duration_seconds` | `service` | Upstream latency histogram |
| `terngi_translation_cache_lookups_total` | `result` (`hit`/`miss`) | Translation cache lookups, one per text |
| `terngi_rate_limited_requests_total` | — | Requests rejected by the rate limiter |

`route` is the route template (e.g. `/v1/translate`), or `unmatched` for unknown paths,
so label values stay bounded. Metrics are per process, like the cache and rate limiter.

### Translate

```bash
curl -X POST http://localhost:8000/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{"content": "Good morning", "from_language": "en", "to_language": "yo"}'
```

### Batch translate

```bash
curl -X POST http://localhost:8000/v1/translate/batch \
  -H 'Content-Type: application/json' -H 'X-API-Key: <your-key>' \
  -d '{"texts": ["Good morning", "Thank you"], "from_language": "en", "to_language": "ig"}'
```

### Detect language

```bash
curl -X POST http://localhost:8000/v1/detect \
  -H 'Content-Type: application/json' \
  -d '{"content": "Ina kwana?"}'
# {"language": "ha", "language_name": "Hausa", "score": 1.0, "is_supported": true}
```

### Converse

```bash
curl -X POST http://localhost:8000/v1/converse \
  -H 'Content-Type: application/json' \
  -d '{
        "content": "Ina kwana?",
        "from_language": "auto",
        "to_language": "en",
        "memory_context": [
          {"role": "user", "content": "My name is Ada"},
          {"role": "assistant", "content": "Nice to meet you, Ada!"}
        ]
      }'
```

Errors use one shape:

```json
{"error": true, "message": "Target language 'fr' not supported. ...", "status_code": 400}
```

## Project layout

```
main.py              FastAPI app and error handlers
middleware.py        Request IDs, API-key auth and rate limiting
config.py            Settings loaded from environment variables
models.py            Pydantic request/response models
routes/              HTTP endpoints
services/            Azure Translator, Groq, cache and language helpers
tests/               Pytest suite (upstream services are mocked)
```

## Development

```bash
pytest --cov          # tests + coverage
ruff check . && ruff format .
mypy .
pre-commit install    # run checks automatically on every commit
```

CI runs lint, type checks, tests on Python 3.10–3.13, a Docker smoke test, secret scanning
and a dependency audit on every pull request.

## Contributing

Contributions of every size are welcome, and you don't need to be an expert:

- 🟢 **New here?** Pick a [good first issue](https://github.com/Terngi-AI/tergniai-multilang/labels/good%20first%20issue).
- 🗣️ **Speak Yoruba, Hausa, Igbo or another Nigerian language?** Help review translations
  and build our [evaluation set](https://github.com/Terngi-AI/tergniai-multilang/labels/languages). Native speakers are our most valuable contributors.
- 🛠️ **Experienced developer?** See [help wanted](https://github.com/Terngi-AI/tergniai-multilang/labels/help%20wanted) for streaming, Redis, speech and more.
- 💬 **Questions or ideas?** Start a conversation in [Discussions](https://github.com/Terngi-AI/tergniai-multilang/discussions).

Read [CONTRIBUTING.md](CONTRIBUTING.md) to get set up in a few minutes, and follow our
[Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately as described in
[SECURITY.md](SECURITY.md).

### Contributors

<a href="https://github.com/Terngi-AI/tergniai-multilang/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Terngi-AI/tergniai-multilang" alt="Contributors" />
</a>

## License

[MIT](LICENSE)
