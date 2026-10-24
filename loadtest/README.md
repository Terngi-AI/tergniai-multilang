# Load testing

This folder contains a repeatable Locust test for the API and a small FastAPI mock for the
upstream providers. It is intentionally separate from the application: running it does not
need Azure, Groq or MORENA credentials.

The scenario covers the paths from issue #44:

- `GET /health`
- `POST /v1/translate` with a cold cache (unique text)
- `POST /v1/translate` with a warm cache (small fixed phrase set)
- `POST /v1/chat`
- `POST /v1/agent`

## Start the mock upstream

From the repository root:

```bash
python -m venv .venv-loadtest
source .venv-loadtest/bin/activate
pip install -r requirements.txt -r loadtest/requirements.txt
uvicorn loadtest.mock_upstream:app --host 127.0.0.1 --port 9001
```

`MOCK_LATENCY_MS` adds a fixed delay to every mock response, which is useful for checking
how upstream latency propagates through the API:

```bash
MOCK_LATENCY_MS=50 uvicorn loadtest.mock_upstream:app --host 127.0.0.1 --port 9001
```

## Start the API against the mock

In a second terminal, configure the app to use the mock. This profile keeps Azure first for
translation, Groq for chat/agent, and still has MORENA available as a translation fallback.

```bash
export ENV_FILE=/dev/null
export AZURE_TRANSLATOR_KEYS=loadtest
export AZURE_TRANSLATOR_ENDPOINT=http://127.0.0.1:9001
export LLM_PROVIDERS=groq,morena
export GROQ_API_KEYS=loadtest
export GROQ_MODELS=loadtest-model
export GROQ_BASE_URL=http://127.0.0.1:9001/openai/v1
export MORENA_BASE_URL=http://127.0.0.1:9001/morena
export TRANSLATION_PROVIDERS=azure,morena,groq
export CHAT_PROVIDERS=groq
export AGENT_PROVIDERS=groq
export DETECTION_PROVIDERS=azure,groq
# Locust sends traffic far faster than the default 60 requests/minute per client.
export RATE_LIMIT_PER_MINUTE=0
uvicorn main:app --host 127.0.0.1 --port 8766
```

On Windows PowerShell, set the same values with `$env:NAME = "value"` and use
`$env:ENV_FILE = "nul"`.

To exercise the MORENA path instead of Azure, clear the Azure key and put MORENA first:

```bash
export AZURE_TRANSLATOR_KEYS=
export TRANSLATION_PROVIDERS=morena,groq
```

## Run Locust

In a third terminal, with the load-test virtualenv active:

```bash
locust -f loadtest/locustfile.py \
  --host http://127.0.0.1:8766 \
  --headless -u 20 -r 5 -t 30s \
  --only-summary \
  --csv /tmp/terngi-loadtest
```

Useful variations:

```bash
# More users, longer run
locust -f loadtest/locustfile.py --host http://127.0.0.1:8766 \
  --headless -u 50 -r 10 -t 120s --only-summary

# Add 50 ms of latency to every mock provider response
MOCK_LATENCY_MS=50 uvicorn loadtest.mock_upstream:app --port 9001

# Run against an instance that requires an API key
LOADTEST_API_KEY=your-key locust -f loadtest/locustfile.py --host https://your-host
```

The CSV output has one row per task name, so cache hits and misses can be compared directly.
Do not commit generated CSV/HTML files.

## Reading the results

- **Requests/s** is aggregate throughput against one API process.
- **95th percentile** shows tail latency; compare `cache hit` with `cache miss` to see the
  upstream and serialization cost.
- **Failures** should be zero. A `503` usually means the provider environment was not passed
  to the API process; a `429` means the client rate limit is lower than the load test rate.
- The mock is deliberately cheap, so results measure the API's own overhead (routing,
  validation, JSON, provider client setup, agent loop) rather than external providers.

Known bottlenecks to watch, and follow-up opportunities:

- Both the Azure and LLM clients create a new `httpx.AsyncClient` per upstream call. That is
  fine at low traffic but adds connection setup cost under load; a shared client is tracked
  separately (see issue #45).
- `/v1/chat` and `/v1/agent` make one model call plus translation calls in some language
  combinations, so their latency is naturally higher than `/v1/translate` cache hits.
- The agent is bounded by `AGENT_MAX_STEPS`; a mock that returns tool calls makes room for
  testing multi-step behaviour, but the default mock answers directly to keep runs stable.

Measured results on the development machine are in [RESULTS.md](RESULTS.md).
