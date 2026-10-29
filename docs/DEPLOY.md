# Deploy Terngi AI for a public demo

This guide runs the API on a small public host so people can try `/chat` without a
server of your own. All three options below use the repository's `Dockerfile`.

> **Free-tier check (October 2026).** Hosting free tiers change often. Render still
> offers a free web service. Hugging Face now requires a paid plan to create a new
> Docker Space on a personal account (the CPU Basic hardware itself is free). Fly.io
> no longer offers a free tier to new accounts, only a short trial. Check the pricing
> links before you start, and see [Free-tier limits](#free-tier-limits).

## Before you deploy

1. Create a [Groq API key](https://console.groq.com/keys). Groq is the default chat and
   agent provider and has a free tier.
2. Optionally create an [Azure Translator key](https://learn.microsoft.com/azure/ai-services/translator/)
   for translation and language detection. Without Azure, add an LLM provider to
   `TRANSLATION_PROVIDERS`.
3. Generate a long random value for `API_KEYS`. Clients send it in the `X-API-Key`
   header. Never reuse a production key for a public demo. If `API_KEYS` is empty, the
   app **refuses to start** unless `ALLOW_UNAUTHENTICATED=true` (local development only).
4. Do not commit `.env` or put keys in the Dockerfile. Set them as host secrets.

The minimum configuration for a demo is:

```dotenv
GROQ_API_KEYS=gsk_...
LLM_PROVIDERS=groq
API_KEYS=<long-random-demo-key>
RATE_LIMIT_PER_MINUTE=30
RATE_LIMIT_MAX_WAIT_SECONDS=0
MAX_CONTENT_LENGTH=2000
MAX_BATCH_SIZE=10
MAX_BATCH_CHARACTERS=10000
MAX_REQUEST_BYTES=262144
CACHE_MAX_ITEMS=500
CONVERSATION_MAX_MESSAGES=20
```

`RATE_LIMIT_MAX_WAIT_SECONDS=0` makes requests fail fast instead of waiting when a
provider is rate-limited. If you also configure Azure, add:

```dotenv
AZURE_TRANSLATOR_KEYS=...
AZURE_TRANSLATOR_LOCATION=global
TRANSLATION_PROVIDERS=azure,groq
DETECTION_PROVIDERS=azure,groq
```

Use the region shown on the Translator resource. A regional resource usually needs its
region (for example `westeurope`), not `global`.

## Option 1: Render (recommended for a new free account)

Render's free web service sleeps after 15 minutes without traffic and has only 512 MB
of RAM. Render may ask you to verify a payment method even when you stay on the free
instance.

1. In the [Render dashboard](https://dashboard.render.com/), choose **New → Web Service**
   and connect your fork of this repository.
2. Set **Language** to **Docker**, choose the `develop` branch, and select the **Free**
   instance type.
3. Under **Advanced**, set the **Docker Command** to:

   ```bash
   uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers
   ```

   Render assigns `$PORT`; the repository's Dockerfile listens on 8000 by default.
   Do not set `PORT` yourself.

4. Set **Health Check Path** to `/health`.
5. Add the environment variables from [Before you deploy](#before-you-deploy) under
   **Environment**. Add `GROQ_API_KEYS` and `API_KEYS` as secrets.
6. Deploy, then check:

   ```bash
   curl https://YOUR-SERVICE.onrender.com/health
   curl https://YOUR-SERVICE.onrender.com/health/ready
   ```

   `/health` is a liveness probe and always returns quickly. `/health/ready` returns
   `ready`, `degraded`, or `not_ready` (HTTP 503 when no core provider is configured);
   with `API_KEYS` set, add the key to see the per-service details:

   ```bash
   curl -H "X-API-Key: <key>" https://YOUR-SERVICE.onrender.com/health/ready
   ```

7. Open `https://YOUR-SERVICE.onrender.com/chat`. If `API_KEYS` is set, paste the demo
   key into **Settings → API key** in the chat page.

### Render free-tier limits

- 512 MB RAM and 0.1 CPU: enough for the API, not for MORENA.
- The service spins down after 15 minutes idle; the next request takes about a minute.
- Free services share 750 instance hours per workspace per month. If those run out, all
  free services in the workspace are suspended until the next month.
- The filesystem is ephemeral. In-memory conversations and the translation cache are
  lost on restart. Set `REDIS_URL` to an external Redis only if your plan allows it;
  the application still works without Redis.
- Free instance hours are limited per workspace. See
  [Render's free-tier documentation](https://render.com/docs/free).

## Option 2: Hugging Face Spaces (Docker Space)

Hugging Face CPU Basic hardware is free and includes 2 vCPU and 16 GB RAM, but creating
a new Docker Space currently requires a paid plan for personal accounts. If you already
have access, this is the best free-hardware option for running MORENA next to the API.

1. Create a **Docker** Space at [huggingface.co/new-space](https://huggingface.co/new-space)
   with **CPU Basic** hardware.
2. Clone the empty Space and add this project:

   ```bash
   git clone https://huggingface.co/spaces/YOUR_USER/YOUR_SPACE
   cd YOUR_SPACE
   git remote add source https://github.com/Terngi-AI/tergniai-multilang.git
   git fetch source develop:refs/remotes/source/develop
   git checkout -B main source/develop
   ```

3. Replace the Space's `README.md` with the Space metadata. The `app_port` must match
   the port in the Dockerfile (8000):

   ```markdown
   ---
   title: Terngi AI
   emoji: 🌍
   colorFrom: green
   colorTo: blue
   sdk: docker
   app_port: 8000
   pinned: false
   ---

   Terngi AI demo
   ```

4. Commit and push to the Space. This replaces the fresh Space's initial commit, so use
   `--force` only on a new Space:

   ```bash
   git add .
   git commit -m "Deploy Terngi AI"
   git push --force origin main
   ```

5. In the Space's **Settings → Variables and secrets**, add the variables from
   [Before you deploy](#before-you-deploy). Use **secrets** for `GROQ_API_KEYS`,
   `AZURE_TRANSLATOR_KEYS`, and `API_KEYS`.
6. Wait for the build, then open `https://YOUR_USER-YOUR_SPACE.hf.space/chat`.

### Hugging Face limits

- Free hardware sleeps when unused and has 50 GB of non-persistent disk.
- Outbound network access is limited to ports 80, 443, and 8080. A Redis server on port
  6379 will not be reachable; use in-memory storage or a TLS endpoint on an allowed port.
- The API is publicly reachable. Keep `API_KEYS` set and rate limits low.
- A new Docker Space may require a paid plan on a personal account; CPU Basic itself is
  free. Check the Space creation page before you start.
- See [Spaces hardware](https://huggingface.co/docs/hub/spaces-overview#hardware-resources)
  and [Spaces configuration](https://huggingface.co/docs/hub/spaces-config-reference).

### Optional: MORENA on Hugging Face

MORENA is a 1.5B model (about 0.9 GB in 4-bit). It does not fit in Render's 512 MB free
instance, but it fits comfortably on Hugging Face CPU Basic.

1. Create a second Docker Space from the `ghcr.io/ggml-org/llama.cpp:server-b11854` image
   (the same versioned, digest-pinned build used in `docker-compose.yml`; see
   [CONTRIBUTING.md](../CONTRIBUTING.md) for how to pick a newer build) with the command
   used in `docker-compose.yml` (or run MORENA on your own machine).
2. Note the Space URL, for example `https://YOUR_USER-morena.hf.space`.
3. On the API Space, add:

   ```dotenv
   MORENA_BASE_URL=https://YOUR_USER-morena.hf.space
   LLM_PROVIDERS=groq,morena
   TRANSLATION_PROVIDERS=morena,groq
   ```

   Keep Groq in the chain as a fallback for languages MORENA does not cover and for
   when the second Space is asleep.

Running the API and MORENA in the same container requires a process manager and is not
covered by this guide. A separate Space keeps each process simple and restartable.

## Option 3: Fly.io (not free for new accounts)

Fly.io is useful if you have legacy free allowances or want a small paid deployment.
New accounts get a limited trial and then pay as you go. The smallest always-on machine
costs a few dollars per month; check [Fly.io pricing](https://fly.io/docs/about/pricing/).
Legacy accounts with the old free allowances can still follow these steps.

```bash
fly launch --no-deploy
```

Set `internal_port = 8000` in the generated `fly.toml`:

```toml
[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0
```

Then set secrets and deploy:

```bash
fly secrets set GROQ_API_KEYS=gsk_... API_KEYS=<long-random-demo-key>
fly deploy
```

Set the health check path to `/health` if `fly launch` asks for one. `auto_stop_machines`
gives you scale-to-zero behaviour, at the cost of a cold start. Do not run MORENA on the
smallest machine; use a machine with at least 1 GB of RAM or a separate service.

## Protect a public demo

- **Always set `API_KEYS`** for a public deployment. Without it, anyone who finds the URL
  can spend your provider quota. The app refuses to start with `API_KEYS` empty unless
  `ALLOW_UNAUTHENTICATED=true`, and `/health/ready` reports `"auth": false` so monitoring
  can alert.
- Use a dedicated demo key. Rotate it if it leaks, and keep production keys separate.
- Keep the request limits small (`MAX_CONTENT_LENGTH`, `MAX_BATCH_SIZE`,
  `MAX_BATCH_CHARACTERS`, `MAX_REQUEST_BYTES`).
- Set `RATE_LIMIT_PER_MINUTE` low and `RATE_LIMIT_MAX_WAIT_SECONDS=0`.
- Set `CORS_ORIGINS` only if a browser app on another origin calls the API. The built-in
  `/chat` page is same-origin and does not need it.
- The bundled `docker compose` Redis runs without persistence, so chat text never lands
  on its disk. If you point `REDIS_URL` at an external Redis with persistence or
  snapshots enabled, conversation text will be written to that server's disk and survive
  in its backups: you own its encryption at rest and backup retention.
- The health probes stay public (load balancers); `/health/ready` shows its per-service
  details only to callers with a valid `API_KEYS` key. `/metrics` requires an API key when
  authentication is configured — give your monitoring stack a dedicated `METRICS_TOKEN`
  instead, and keep both behind your proxy or firewall if the deployment is not a
  throwaway demo.
- Review [SECURITY.md](../SECURITY.md) before exposing a production instance, and work
  through the full threat model and operator checklist in
  [THREAT_MODEL.md](THREAT_MODEL.md).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `401 Missing or invalid API key` | Send `X-API-Key`, or paste the key into `/chat` → Settings |
| `503 Agent is not configured` / `Translation service is not configured` | No provider keys, or the provider name is missing from `LLM_PROVIDERS` |
| `502 Translation service error` with Azure `401` | The Azure key is revoked, or `AZURE_TRANSLATOR_LOCATION` does not match a regional resource |
| First request takes about a minute | The free instance was asleep; this is expected |
| Conversations disappear after a restart | Free hosts have ephemeral storage and no shared Redis |
| `429` from a provider | Provider quota or the app's rate limit; add another key/provider or lower traffic |

## Free-tier limits

| Host | Free for a new account? | Sleep / cold start | RAM | Notes |
|---|---|---|---|---|
| Render | Yes, free web service | 15 min idle, about 1 min | 512 MB | Best default for this API |
| Hugging Face Spaces | CPU Basic is free; Docker Space creation may require a paid plan | Sleeps when unused | 16 GB | Good for MORENA; check current plan rules |
| Fly.io | No; trial only for new accounts | Configurable scale-to-zero | Machine-dependent | Cheap paid option; legacy allowances vary |

Links: [Render free tier](https://render.com/docs/free),
[Hugging Face Spaces](https://huggingface.co/docs/hub/spaces-overview),
[Fly.io pricing](https://fly.io/docs/about/pricing/).
