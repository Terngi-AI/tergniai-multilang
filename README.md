# Terngi AI — Translation & Conversation API

[![CI](https://github.com/Terngi-AI/tergniai-multilang/actions/workflows/ci.yml/badge.svg)](https://github.com/Terngi-AI/tergniai-multilang/actions/workflows/ci.yml)
[![Security](https://github.com/Terngi-AI/tergniai-multilang/actions/workflows/security.yml/badge.svg)](https://github.com/Terngi-AI/tergniai-multilang/actions/workflows/security.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Terngi-AI/tergniai-multilang/badge)](https://scorecard.dev/viewer/?uri=github.com/Terngi-AI/tergniai-multilang)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%E2%80%933.13-blue)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Good first issues](https://img.shields.io/github/issues/Terngi-AI/tergniai-multilang/good%20first%20issue?label=good%20first%20issues&color=7057ff)](https://github.com/Terngi-AI/tergniai-multilang/labels/good%20first%20issue)
[![GitHub stars](https://img.shields.io/github/stars/Terngi-AI/tergniai-multilang?style=social)](https://github.com/Terngi-AI/tergniai-multilang/stargazers)

**Open-source translation and AI conversation for Nigerian languages.**

A **conversational AI** and translation API for **96 languages**, built
African-first: Yoruba, Hausa, Igbo, Nigerian Pidgin, Swahili, Amharic, isiZulu and 20 more
African languages, plus Arabic, Chinese, Spanish, French, Hindi, Japanese, Polish, Dutch, Irish
and the other major world languages. It can use several providers at once:
[Azure Translator](https://learn.microsoft.com/azure/ai-services/translator/),
[Groq](https://groq.com/) or any OpenAI-compatible API, and
[MORENA](https://huggingface.co/vamboai/morena-1.5b-instruct), an open African-language model
you can run for free.

## Why this project?

More than 100 million people speak Yoruba, Hausa or Igbo, yet these languages are still
poorly served by most software. Terngi AI gives developers a simple, self-hostable API to
build apps, chatbots and services that speak to people in their own language, and it is
built in the open so native speakers and developers can improve it together.

⭐ **If this is useful to you, star the repo** — it helps more people find it.

## Features

- **Chat like any AI assistant**: `/v1/chat` and a built-in web chat at `/chat`. Talk about
  anything in any supported language; it remembers the conversation and you can switch
  languages mid-chat
- **AI agent** (`/v1/agent`) that uses tools (translation, language detection, time) behind
  the scenes, see [docs/AGENT.md](docs/AGENT.md)
- **Multiple providers, models and keys** — Azure, Groq, OpenRouter, Together, Cerebras,
  Hugging Face, Ollama or MORENA, tried in order; keys rotate and failing keys, models or
  providers are skipped automatically. Which user data each provider receives, and its
  retention and training terms: [docs/DATA.md](docs/DATA.md)
- **WhatsApp bot**: people message your WhatsApp number in any supported language and get
  answers in that language, with memory; plus an endpoint to send messages. See
  [docs/WHATSAPP.md](docs/WHATSAPP.md)
- **Free, local African-language model** — run [MORENA](docs/MORENA.md) with llama.cpp
- **Translate** text between any two supported languages, one at a time or in batches
- **Auto-detect** the source language — pass `"from_language": "auto"` to any endpoint
- **Converse** in any supported language; the reply comes back in the target language,
  with optional multi-turn memory (`memory_context`)
- **Translation cache** (in-memory TTL/LRU) to save quota on repeated phrases
- **Opt-in feedback** for building an open translation evaluation set
- **API-key authentication** (`X-API-Key`) and **per-client rate limiting**
- **Request IDs** (`X-Request-ID`) and timing headers for tracing
- Input validation, upstream timeouts and consistent JSON error responses
- Liveness (`/health`) and readiness (`/health/ready`) probes
- Docker image with a health check, running as a non-root user

## Quick start

### Prerequisites

- Python 3.11+
- At least one provider: a [Groq API key](https://console.groq.com/keys) (free tier),
  [MORENA running locally](docs/MORENA.md) (free), an Azure Translator key, or any
  OpenAI-compatible API

### Run locally

```bash
git clone https://github.com/Terngi-AI/tergniai-multilang.git
cd tergniai-multilang
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock

cp .env.example .env   # then fill in your keys
uvicorn main:app --reload
```

Open **http://localhost:8000/chat** to chat in your browser, or
http://localhost:8000/docs for the interactive API docs.

### Run with Docker

```bash
docker build -t terngi-ai .
docker run --rm -p 8000:8000 --env-file .env terngi-ai
```

### Run with Docker Compose (API + Redis)

```bash
docker compose up
```

Starts the API with Redis, so the cache, rate limits and chat conversations are shared and
survive API container restarts. The Redis service runs **without persistence** (no RDB
snapshots, no AOF, no volume): everything it holds is short-lived by design, and we do not
want chat text written to disk where it would outlive the keys' TTL. For longer-lived
shared storage, point `REDIS_URL` at an external Redis you manage. The Redis service also
has a 512 MB `volatile-lru` limit as a safety net; conversation storage independently
enforces `CONVERSATION_MAX_ITEMS`.

### Deploy a public demo

See [docs/DEPLOY.md](docs/DEPLOY.md) for current free/cheap hosting options (Render,
Hugging Face Spaces, Fly.io), secret/rate-limit settings, and free-tier caveats.

### Run with MORENA (free, no API keys needed)

```bash
docker compose --profile morena up
```

This starts the API and a llama.cpp server with MORENA 1.5B (downloaded on first start,
about 0.9 GB). See [docs/MORENA.md](docs/MORENA.md).

## Configuration

All configuration comes from environment variables (see [`.env.example`](.env.example)).

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_TRANSLATOR_KEYS` | no* | — | Azure Translator keys (comma-separated, rotated) |
| `AZURE_TRANSLATOR_ENDPOINT` | no | `https://api.cognitive.microsofttranslator.com` | Translator endpoint |
| `AZURE_TRANSLATOR_LOCATION` | no | `global` | Azure resource region |
| `LLM_PROVIDERS` | no | `groq` | LLM providers in priority order |
| `<NAME>_API_KEYS` | yes* | — | Keys for a provider, e.g. `GROQ_API_KEYS=k1,k2` (`<NAME>_API_KEY` also works) |
| `<NAME>_MODELS` | no | provider default | Models to try in order, e.g. `GROQ_MODELS=openai/gpt-oss-120b,openai/gpt-oss-20b` |
| `<NAME>_BASE_URL` | for custom providers | preset | OpenAI-compatible base URL |
| `CHAT_PROVIDERS` | no | `LLM_PROVIDERS` | Providers used for `/v1/converse` |
| `TRANSLATION_PROVIDERS` | no | `azure` + `LLM_PROVIDERS` | Providers used for translation, in order |
| `DETECTION_PROVIDERS` | no | `azure` + LLM providers except MORENA | Providers used for language detection |
| `AGENT_PROVIDERS` | no | OpenAI-compatible chat providers | Providers that run the agent (must support tool calling) |
| `AGENT_MAX_STEPS` | no | `6` | Max model turns per agent request |
| `AGENT_MAX_TOKENS` | no | `1500` | Max tokens per agent model call (bounds the cost of a multi-step request) |
| `CONVERSATION_TTL_SECONDS` | no | `86400` | How long chats are remembered after the last message |
| `CONVERSATION_MAX_ITEMS` | no | `10000` | Maximum conversations kept; the least recently written are evicted first |
| `CONVERSATION_MAX_MESSAGES` | no | `40` | Messages kept per conversation |
| `CONVERSATION_MAX_CHARS` | no | `20000` | Characters of history kept per conversation; the oldest turns are dropped first |
| `REDIS_URL` | no | *(in-memory)* | Redis for shared cache, rate limits and conversations, e.g. `redis://localhost:6379/0` |
| `REDIS_PREFIX` | no | `terngi:` | Prefix for every Redis key |
| `REDIS_TIMEOUT` | no | `2` | Redis connect/read timeout in seconds |
| `PROVIDER_DOWN_COOLDOWN_SECONDS` | no | `30` | How long to skip a provider whose server can't be reached |
| `RATE_LIMIT_MAX_WAIT_SECONDS` | no | `10` | When every model is rate-limited, wait this long for one to free up |
| `<NAME>_LANGUAGES` | no | all (MORENA: its 14) | Restrict a provider to certain languages |
| `KEY_COOLDOWN_SECONDS` | no | `60` | How long to skip a rate-limited key |
| `INVALID_KEY_COOLDOWN_SECONDS` | no | `3600` | How long to skip a rejected key |
| `REQUEST_TIMEOUT` | no | `30` | Upstream timeout in seconds |
| `REQUEST_DEADLINE_SECONDS` | no | `55` | Whole-request wall-clock budget for JSON responses; retries, fallbacks and agent steps share it (`0` disables) |
| `STREAM_DEADLINE_SECONDS` | no | `120` | Whole-request budget for streaming responses (`0` disables) |
| `STREAM_HEARTBEAT_SECONDS` | no | `15` | `/v1/chat/stream` sends an SSE keep-alive comment at most this often, so idle proxies don't cut long streams (`0` disables) |
| `STREAM_QUEUE_MAXSIZE` | no | `256` | Pending events per stream; a client that reads slowly pauses generation (backpressure) instead of growing memory (`0` removes the bound) |
| `REQUEST_MAX_UPSTREAM_ATTEMPTS` | no | `20` | Maximum upstream requests per API request, retries and fallbacks included (`0` disables) |
| `UPSTREAM_MAX_RETRIES` | no | `2` | Retries for upstream `5xx`/connection errors (all providers) and Azure `429`s; `0` disables. LLM `429`s rotate to the next key or model instead |
| `UPSTREAM_RETRY_BASE_DELAY` | no | `0.5` | First backoff step in seconds; doubles each retry, with full jitter |
| `UPSTREAM_RETRY_MAX_DELAY` | no | `10` | Longest wait between retries; a longer `Retry-After` fails fast |
| `MAX_CONTENT_LENGTH` | no | `5000` | Max characters per message |
| `MAX_MEMORY_MESSAGES` | no | `20` | Max turns in `memory_context` |
| `API_KEYS` | no | *(auth disabled)* | Comma-separated client keys accepted in `X-API-Key` |
| `METRICS_TOKEN` | no | *(off)* | Optional dedicated bearer token for `/metrics` (`Authorization: Bearer ...`), so the monitoring stack needs no API key |
| `WHATSAPP_*` | no | *(off)* | WhatsApp bot settings, see [docs/WHATSAPP.md](docs/WHATSAPP.md) |
| `RATE_LIMIT_PER_MINUTE` | no | `60` | Requests per minute per client; `0` disables |
| `AUTH_FAILURES_PER_MINUTE` | no | `10` | Failed API-key attempts allowed per IP per minute; `0` disables |
| `CACHE_TTL_SECONDS` | no | `3600` | Translation cache lifetime; `0` disables |
| `CACHE_MAX_ITEMS` | no | `1000` | Max cached translations |
| `MAX_BATCH_SIZE` | no | `25` | Max texts per batch request |
| `MAX_BATCH_CHARACTERS` | no | `50000` | Max total characters per batch |
| `MAX_REQUEST_BYTES` | no | `1048576` | Largest request body accepted; bigger requests get `413` |
| `CORS_ORIGINS` | no | *(disabled)* | Comma-separated allowed origins |
| `FORWARDED_ALLOW_IPS` | no | `127.0.0.1,::1` | Proxy IPs/CIDRs trusted to set `X-Forwarded-For` |
| `LOG_LEVEL` | no | `INFO` | Python log level. Upstream error *bodies* are only logged at `DEBUG` (they can echo user text); `INFO` logs the status, error code and request ID |

\* You need at least one provider. Built-in provider names are `groq`, `openrouter`,
`together`, `cerebras`, `huggingface`, `openai`, `ollama` and `morena`; any other name works
when you set `<NAME>_BASE_URL` to an OpenAI-compatible API.

**How fallback works:** for each request, providers are tried in order. Within a provider,
each model is tried in order, and keys rotate between requests. A key that is rejected
(401/403) or rate-limited (429) is skipped for a while; a model that errors or returns
unusable output is skipped for that request. The app starts without keys; endpoints with
no configured provider return `503`.

JSON requests share one `REQUEST_DEADLINE_SECONDS` wall-clock budget and one
`REQUEST_MAX_UPSTREAM_ATTEMPTS` cap across retries, provider fallbacks and agent steps.
Streaming responses use `STREAM_DEADLINE_SECONDS`. Exhausting the deadline returns `504`;
exhausting the attempt cap returns `503`, both with `Retry-After`. The WhatsApp webhook is
excluded from the hard request deadline because Meta must get an immediate answer; each
background reply starts its own `REQUEST_DEADLINE_SECONDS` budget.

Example, using two Groq keys, OpenRouter as a backup and MORENA for translation:

```bash
LLM_PROVIDERS=groq,openrouter,morena
GROQ_API_KEYS=gsk_key_one,gsk_key_two
GROQ_MODELS=openai/gpt-oss-120b,openai/gpt-oss-20b
OPENROUTER_API_KEYS=sk-or-...
OPENROUTER_MODELS=meta-llama/llama-3.3-70b-instruct
TRANSLATION_PROVIDERS=morena,groq,openrouter
```

### Running behind a reverse proxy

Set `FORWARDED_ALLOW_IPS` to the proxy's IPs or CIDRs (comma-separated), for example the
ALB/Nginx address or the Docker network subnet. Uvicorn trusts `X-Forwarded-For` only from
those peers; requests from anywhere else keep their direct peer address, so a client cannot
spoof its identity. Without this setting, every anonymous client behind the proxy shares one
rate-limit bucket and one conversation owner. Do not use `*` unless the API port is reachable
only through the proxy.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | API info and supported languages |
| `GET` | `/health` | Liveness probe |
| `GET` | `/health/ready` | Readiness probe (public status; per-service details require a key) |
| `GET` | `/metrics` | Prometheus metrics (requires a key or `METRICS_TOKEN` when auth is on) |
| `GET` | `/v1/languages` | Supported language codes |
| `POST` | `/v1/translate` | Translate text |
| `POST` | `/v1/translate/batch` | Translate up to 25 texts in one request |
| `POST` | `/v1/detect` | Detect the language of a text |
| `POST` | `/v1/feedback` | Rate a translation or chat reply (opt-in) |
| `POST` | `/v1/converse` | Translate and get an LLM reply |
| `POST` | `/v1/agent` | The assistant without server memory (send `history` yourself) |
| `POST` | `/v1/chat` | **Chat** with memory: send `message` and `conversation_id` |
| `POST` | `/v1/chat/stream` | The same chat, streamed word by word as Server-Sent Events |
| `GET` / `DELETE` | `/v1/chat/{id}` | Read or forget a conversation |
| `GET` | `/chat` | Web chat page |

📖 **Full usage guide with curl, Python and JavaScript examples: [docs/USAGE.md](docs/USAGE.md)**

### Authentication & rate limits

When `API_KEYS` is set, every `/v1/*` endpoint except `/v1/languages` requires an
`X-API-Key` header. Each client (API key, or IP address when no key is sent) may make
`RATE_LIMIT_PER_MINUTE` requests per minute. Responses include `X-RateLimit-Limit` and
`X-RateLimit-Remaining`; when exceeded you get `429` with a `Retry-After` header.

> By default the cache, rate limiter and chat conversations live in each server process's
> memory. Set `REDIS_URL` to share them between replicas (`docker compose up` does this
> for you; the compose Redis runs without persistence, so nothing is written to disk).
> If you point it at an external Redis with persistence enabled, conversation text will
> be written to that server's disk and backups: you then own its encryption at rest and
> backup retention.

### Metrics

`GET /metrics` serves Prometheus metrics. When `API_KEYS` is configured, scraping requires a
valid `X-API-Key` — or, better, a dedicated `METRICS_TOKEN` sent as
`Authorization: Bearer <token>`, so the monitoring stack holds no key that can call the
API. Without `API_KEYS` (local development) the endpoint is public. It is never rate
limited. Scrape example:

```
http_get:
  url: http://terngi:8000/metrics
  headers:
    Authorization: "Bearer <METRICS_TOKEN>"
```

| Metric | Labels | Description |
|---|---|---|
| `terngi_http_requests_total` | `method`, `route`, `status` | Requests handled, including `401`/`429` rejections and unhandled `500`s |
| `terngi_http_request_duration_seconds` | `method`, `route` | Request latency histogram |
| `terngi_upstream_requests_total` | `service` (`azure` or the LLM provider name, e.g. `groq`, `openrouter`, `morena`), `outcome` (`success`/`error`) | Upstream calls |
| `terngi_upstream_request_duration_seconds` | `service` | Upstream latency histogram |
| `terngi_translation_cache_lookups_total` | `result` (`hit`/`miss`) | Translation cache lookups, one per text |
| `terngi_rate_limited_requests_total` | — | Requests rejected by the rate limiter |
| `terngi_auth_failures_total` | `outcome` (`invalid`/`throttled`) | Invalid API keys, and failed attempts throttled by the per-IP limiter |

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

### Glossary

Both translation endpoints accept an optional `glossary`: a map of source terms to a
translation for every target language (`"Terngi": "Terngi"`) or to per-language translations
(`"mobile money": {"ha": "kudin waya", "yo": "owo alagbeka"}`). A term mapped to itself is
protected from translation; entries for other target languages are ignored.

```bash
curl -X POST http://localhost:8000/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{
    "content": "Welcome to Terngi, where you can pay with mobile money",
    "from_language": "en",
    "to_language": "ha",
    "glossary": {
      "Terngi": "Terngi",
      "mobile money": {"ha": "kudin waya"}
    }
  }'
```

Azure Translator receives the terms as dynamic-dictionary markup, language models get them in
the prompt and MORENA uses placeholders around protected terms. The glossary is part of the
cache key, so the same text with different glossaries is translated and cached separately.

### Detect language

```bash
curl -X POST http://localhost:8000/v1/detect \
  -H 'Content-Type: application/json' \
  -d '{"content": "Ina kwana?"}'
# {"language": "ha", "language_name": "Hausa", "score": 1.0, "is_supported": true}
```

### Chat

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Hi! My name is Chidi and I sell tomatoes in Enugu market."}'
# {"conversation_id": "3f9c…", "reply": "Hello Chidi! How can I help you today?", ...}

# Continue in any language; it remembers
curl -X POST http://localhost:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Kedu aha m?", "conversation_id": "3f9c…"}'
# {"reply": "Aha gị bụ Chidi.", "language": "ig", ...}
```

### Agent

```bash
curl -X POST http://localhost:8000/v1/agent \
  -H 'Content-Type: application/json' \
  -d '{"message": "Nnọọ! Kedu ụbọchị taa?"}'
# {"answer": "Ụtụtụ ọma! Taa bụ Mọnde, Ọktoba 19, 2026.", "language": "ig", "reply_language": "ig",
#  "steps": [{"tool": "get_current_time", ...}, {"tool": "translate", ...}]}
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

### WhatsApp

Connect a WhatsApp number and Terngi AI answers people there in their own language. Setup,
commands and sending: [docs/WHATSAPP.md](docs/WHATSAPP.md).

```bash
curl -X POST http://localhost:8000/v1/whatsapp/send -H 'Content-Type: application/json' \
  -d '{"to": "+447700900123", "text": "Your order is ready.", "to_language": "yo"}'
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
services/            Providers (Azure, LLMs, MORENA), key rotation, cache, language helpers
docs/                Usage guide, agent design, running MORENA
tests/               Pytest suite (upstream services are mocked)
```

## Development

```bash
pytest --cov          # tests + coverage
ruff check . && ruff format .
mypy .
pre-commit install    # run checks automatically on every commit
```

CI runs lint, type checks, tests on Python 3.11–3.13 and a Docker smoke test on every pull
request. A separate security workflow scans for malware, secrets, insecure code, vulnerable
dependencies and container issues, and runs simulated attacks against the API, on every PR and
daily. See [SECURITY.md](SECURITY.md#automated-security-scanning).

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
