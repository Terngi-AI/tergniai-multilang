# Load-test results

Measurements taken on 2026-10-24 against `origin/develop` at commit `81963e1`, using the
mock upstream in this folder. The API process, mock process and Locust process were all running
on the same laptop, so these are lower bounds for a dedicated server.

## Environment

- HP EliteBook x360 1030 G2, Intel Core i7-7600U (2 cores / 4 threads), 16 GB RAM
- Windows, API running under Python 3.12.15 with one uvicorn worker
- Locust 2.47.0 (Python 3.14.7), mock upstream on port 9001, API on port 8766
- `MOCK_LATENCY_MS=0`, `RATE_LIMIT_PER_MINUTE=0`, in-memory stores, one API process
- Command: `locust -f loadtest/locustfile.py --host http://127.0.0.1:8766 --headless -u N -r R -t 20s --only-summary`

## Results

| Users | Aggregate req/s | p50 | p95 | Failures |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 16.2 | 37 ms | 140 ms | 0 |
| 20 | 30.0 | 82 ms | 270 ms | 0 |
| 50 | 31.2 | 580 ms | 1800 ms | 0 |

At 20 users the task split was:

| Task | Requests/s | Median | p95 |
| --- | ---: | ---: | ---: |
| `GET /health` | 6.1 | 35 ms | 120 ms |
| `POST /v1/translate` (cache hit) | 8.1 | 55 ms | 200 ms |
| `POST /v1/translate` (cache miss) | 9.5 | 130 ms | 300 ms |
| `POST /v1/chat` | 2.5 | 100 ms | 250 ms |
| `POST /v1/agent` | 3.7 | 140 ms | 270 ms |

At 50 users throughput stopped increasing (about 31 req/s) while p95 rose to 1.8 s. This is
the saturation point on this two-core machine, with Locust and the mock competing for CPU; it
is not a production capacity figure.

## Findings

- The cache-hit path is consistently cheaper than a cache miss (about 55 ms versus 130 ms
  median at 20 users). Translation cache keys and TTL behaviour are worth preserving.
- `POST /v1/chat` and `POST /v1/agent` are the slowest endpoints because they make an upstream
  model call; `/v1/agent` is slightly slower because of its tool loop.
- The first run immediately after starting the API was much slower than a repeat run. Warm up
  the process (and accept one cache miss per phrase) before recording numbers.
- The API and mock were sharing two cores, so latency above ~30 req/s is dominated by local
  CPU contention. Use a separate load generator and a dedicated API host for capacity planning.
- Each upstream call creates a new `httpx.AsyncClient`; a shared client is a likely
  throughput improvement under higher load and is tracked separately in issue #45.

## Reproduce

See [README.md](README.md). Keep the generated CSV files out of git; this file contains only
summarised, machine-agnostic observations.
