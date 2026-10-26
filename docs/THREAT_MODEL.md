# Threat model and operator checklist

This is a threat model for **deploying** Terngi AI: what the operator must protect, what
the application already defends against, and what must be configured. It complements
[SECURITY.md](../SECURITY.md) (vulnerability reporting and the CI security scans) and
[DEPLOY.md](DEPLOY.md) (free hosting options). Last reviewed: 2026-10-25.

## Assets

| Asset | What it is | If compromised |
|---|---|---|
| Provider API keys | `GROQ_API_KEYS`, `AZURE_TRANSLATOR_KEYS`, ... | An attacker spends your paid quota, or the provider suspends you |
| Client API keys | the values in `API_KEYS` | Anyone can use the API as your client, including reading what other flows allow |
| Conversations and WhatsApp memory | user text kept by `/v1/chat` and the WhatsApp bot | Exposure of user content; a GDPR / NDPA incident |
| The WhatsApp business number | `WHATSAPP_PHONE_NUMBER_ID` and its access token | Unauthorised sends from your number, Meta policy violations, number ban |
| Quota and spend | usage on Groq, Azure, OpenRouter, ... | Direct cost, or suspension of the account |
| CI secrets | GitHub Actions secrets used by the release workflow | Compromised build or release images |
| The API host itself | the container or VM running the app | All of the above, plus your network's reputation |

## What the application already defends against

No configuration needed; these are on for every deployment:

- Request bodies over `MAX_REQUEST_BYTES` are rejected with `413`, including streamed
  bodies; text lengths, batch sizes and request deadlines bound what one request can do.
- Per-client rate limiting (API key or IP) and an upstream attempt cap per request.
- API keys are compared in constant time and **never logged**; request bodies are never
  written to logs.
- Security headers on every response, and a strict CSP on the `/chat` page.
- The WhatsApp webhook is verified with Meta's `X-Hub-Signature-256` signature, so webhooks
  can't be forged.
- Conversation history is treated as data, not instructions, and can't inject system
  prompts; the agent has a step limit (`AGENT_MAX_STEPS`).
- Supply chain: locked dependencies installed with checksums, actions pinned to SHAs,
  container images pinned by digest and scanned — see
  [SECURITY.md → Automated security scanning](../SECURITY.md#automated-security-scanning).

## Threats and what the operator must do

| # | Threat | Built-in mitigation | Operator's action |
|---|---|---|---|
| 1 | Unauthenticated public exposure | Authentication switches on as soon as `API_KEYS` is set | Set `API_KEYS` — a public instance without it is an open quota tap |
| 2 | Key leakage (`.env` in git, logs, screenshots) | Keys are never logged; gitleaks and GitHub secret scanning in CI | Use the host's secret store, never commit `.env`, rotate on suspicion — [SECURITY.md → Handling secrets](../SECURITY.md#handling-secrets) |
| 3 | Quota abuse by a hostile or careless client | Rate limits, deadlines, attempt caps, size limits | Keep `RATE_LIMIT_PER_MINUTE` and the `MAX_*` limits small on public instances — [DEPLOY.md → Protect a public demo](DEPLOY.md#protect-a-public-demo) |
| 4 | Prompt injection or abuse through `/v1/chat`, `/v1/agent` | History can't inject system prompts; agent step limit; (abuse detection is tracked in [#38](https://github.com/Terngi-AI/tergniai-multilang/issues/38)) | Keep `AGENT_MAX_STEPS` low; review logs for abuse patterns |
| 5 | Spam or abuse through `/v1/whatsapp/send` | The endpoint requires `X-API-Key`; Meta's 24-hour window and template rules apply | Send only to people who consented, with approved templates — [WHATSAPP.md → Sending messages](WHATSAPP.md#sending-messages) |
| 6 | Data at rest in Redis (cache, conversations, WhatsApp memory) | Redis is optional; keys and owners are stored only as hashes | If you enable it: private network, TLS + password, and no disk persistence visible to anyone — [SECURITY.md → Runtime protections](../SECURITY.md#runtime-protections); compose snapshots are addressed in [#85](https://github.com/Terngi-AI/tergniai-multilang/issues/85) |
| 7 | Logs leak user content | Bodies are never logged | Access logs contain URL paths, and chat paths include conversation IDs — collect logs carefully and keep retention short ([`LOG_LEVEL`](../.env.example)) |
| 8 | The `/chat` web page | Same-origin, strict CSP | It stores the API key in the browser's localStorage, so don't publish `/chat` on a machine shared with untrusted people ([#86](https://github.com/Terngi-AI/tergniai-multilang/issues/86)) |
| 9 | Compromised CI or self-hosted runner | Pinned actions, read-only token, `pull_request` (never `pull_request_target`) triggers, workflow approval for first-time contributors | Approve external runs, keep self-hosted runners patched and isolated — [SECURITY.md → Automated security scanning](../SECURITY.md#automated-security-scanning) |
| 10 | Supply chain: a tampered package, image or action | Hash-locked requirements, pinned action SHAs, digest-pinned images, daily Trivy/OSV/pip-audit scans | Bump the pins when advisories land — [CONTRIBUTING.md → Security checks and dependencies](../CONTRIBUTING.md#security-checks-and-dependencies) |

## Operator checklist

Run through this before exposing the API, and re-check it after every change.

### Before first startup

- [ ] **`API_KEYS` is set** to a long random value (or several). Without it, anyone who
      finds the URL can spend your quota. — [configuration table](../README.md#configuration),
      [DEPLOY.md → Before you deploy](DEPLOY.md#before-you-deploy)
- [ ] **HTTPS in front, and `FORWARDED_ALLOW_IPS` lists your proxy** (never `*` when the
      API port is reachable from the internet). — [README → Running behind a reverse
      proxy](../README.md#running-behind-a-reverse-proxy)
- [ ] **`CORS_ORIGINS` left empty** unless a browser app on another origin genuinely needs
      to call the API. — [`CORS_ORIGINS` in .env.example](../.env.example)
- [ ] **`/metrics` and `/health/ready` are not public** — they reveal configuration and
      traffic. Block them at the proxy for now; optional auth for them is tracked in
      [#87](https://github.com/Terngi-AI/tergniai-multilang/issues/87). — [README →
      Metrics](../README.md#metrics)
- [ ] **If `REDIS_URL` is set: private network, TLS + password, and persistence you can
      protect** (snapshots contain conversations). — [SECURITY.md → Runtime
      protections](../SECURITY.md#runtime-protections)

### Ongoing

- [ ] **Rotate the client keys in `API_KEYS`** on a schedule and immediately on any
      suspected leak; revoking at the provider matters more than cleaning git history. —
      [SECURITY.md → Handling secrets](../SECURITY.md#handling-secrets)
- [ ] **Check each provider's retention and training settings** and enable zero-retention
      options where you can get them (each provider's console; the project tracks the
      terms per provider in `docs/DATA.md`).
- [ ] **Keep log retention short**: access logs carry URL paths, and chat paths include
      the conversation ID. — [`LOG_LEVEL` in .env.example](../.env.example)
- [ ] **Keep a dedicated key per environment**: never reuse a production key on a public
      demo. — [DEPLOY.md → Protect a public demo](DEPLOY.md#protect-a-public-demo)
- [ ] **Bump dependency and image pins** when an advisory lands (the daily scan tells
      you). — [CONTRIBUTING.md → Security checks and dependencies](../CONTRIBUTING.md#security-checks-and-dependencies)

## Out of scope

- Threats to a provider's own infrastructure and data practices — that's covered by each
  provider's terms, summarised in `docs/DATA.md`.
- Model behaviour (hallucination, bias, wrong translations) — a quality problem, not a
  security one.
