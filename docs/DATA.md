# Data: what goes where, and what each provider does with it

Text sent to this API — translations, chat messages, WhatsApp messages — is passed to
third-party AI providers so they can process it. Under GDPR, Nigeria's NDPA and similar
laws, each provider that receives user content is a **data processor**, and the operator
of this deployment is the **data controller**. This page answers three questions:

1. What is sent to which provider?
2. Does the provider keep it, and may it be used for training?
3. What does this API itself store, and for how long?

Provider terms were checked on **2026-10-25**. They change — re-check them before relying
on this page, and update it whenever a provider is added or removed (see
[Keeping this page current](#keeping-this-page-current) at the bottom).

## Data flow

```
client ── user text ──▶ Terngi API ──▶ translation & language detection (Azure, then the
        (HTTP or            │              LLM chain, tried in order with fallbacks)
         WhatsApp)          ├────────▶ chat / agent LLM chain (same providers)
                             │
                             ├────────▶ optional Redis (self-hosted): cache, conversations,
                             │          WhatsApp memory, rate limits
                             └────────▶ Meta WhatsApp API (only when the bot is configured)
```

Cloud providers receive the text over HTTPS and are reached only for the calls that need
them: translation/detection goes through `TRANSLATION_PROVIDERS` / `DETECTION_PROVIDERS`,
chat and agent calls through `LLM_PROVIDERS`. Ollama and MORENA run on your own machine,
so for them nothing leaves your network.

## The providers

What each provider receives, and its current retention and training terms:

| Provider | Sent | Retention / training (per the provider's terms) |
|---|---|---|
| **Azure Translator** (Microsoft) | Text to translate and detect | Governed by the [Microsoft Customer Agreement](https://www.microsoft.com/licensing/docs/view/Microsoft-Customer-Agreement); data handling for the service is described on the [Cognitive Services compliance and privacy page](https://azure.microsoft.com/support/legal/cognitive-services-compliance-and-privacy/) (linked from the [product docs](https://learn.microsoft.com/azure/ai-services/translator/)) and the [Microsoft Trust Center](https://www.microsoft.com/en-us/trust-center). Your endpoint is region-pinned, so you choose where in the cloud the text is processed. A [local container](https://learn.microsoft.com/azure/ai-services/translator/containers/overview) is available if you want no cloud at all. |
| **Groq** | Chat/agent messages (system prompt, history, user text) and translation requests | Customer data is governed by the Groq Services Agreement and the [Customer Data Processing Addendum](https://console.groq.com/docs/legal/customer-data-processing-addendum) (effective 2025-10-15): Groq acts as **processor**, keeps customer data only as long as needed to provide the service, and deletes it on request within 180 days after termination. Current subprocessors: [trust.groq.com](https://trust.groq.com/subprocessors). |
| **OpenRouter** | Chat/agent messages and translation requests, routed to the upstream model provider you select | OpenRouter itself [does not use your inputs or outputs for model training](https://openrouter.ai/privacy) (policy updated 2026-08-31). The request is then handled by the **upstream provider under its own terms** — see [provider routing](https://openrouter.ai/docs/features/provider-routing); models that don't train on your data are labelled where disclosed. [EU in-region routing](https://openrouter.ai/business/eu) is available on the Business tier. |
| **Together** | Chat/agent messages and translation requests | [Privacy policy](https://together.ai/privacy) (updated 2025-12-17): data is **not** used to train models without your explicit opt-in. In the dashboard, Settings → Profile, you can disable storing prompts/responses; opting out of prompt storage enables **Zero Data Retention**: submitted content "is not stored, retained, or used for model training, product improvements, or any secondary purposes" except as needed to serve the request. |
| **Cerebras** | Chat/agent messages and translation requests | [Privacy policy](https://cerebras.ai/privacy-policy) (effective 2024-08-27), section 6: Cerebras "does not retain inputs and outputs associated with our training, inference and chatbot Services"; related logs are deleted when no longer needed. [Trust center](https://trust.cerebras.ai/). |
| **Hugging Face** | Chat/agent messages and translation requests (via the Inference API at `router.huggingface.co`, or a dedicated Inference Endpoint) | Serverless inference is governed by the [privacy policy](https://huggingface.co/privacy) and terms of service. For [Inference Endpoints](https://huggingface.co/docs/inference-endpoints/guides/security): Hugging Face "does not store any customer data in terms of payloads or tokens"; request logs are kept **30 days**; TLS in transit; GDPR DPA via Enterprise Hub; SOC 2 Type 2. |
| **OpenAI** | Chat/agent messages and translation requests | [Data controls guide](https://platform.openai.com/docs/guides/your-data): API data is **not** used to train or improve models (since 2023-03-01, unless you opt in). Abuse-monitoring logs, which can contain prompts and responses, are kept **up to 30 days** by default; approved customers can exclude content from those logs with **Zero Data Retention** or **Modified Abuse Monitoring**. Data residency is available per project (e.g. `eu.api.openai.com` for the EU). |
| **Ollama / MORENA** (llama.cpp) | Chat/agent messages and translation requests | No third party: the models run on your own machine, so user text never leaves your network. Keep the server's port private. See [docs/MORENA.md](MORENA.md). |

> OpenRouter and any custom provider route your request to *another* company's models.
> What matters for your compliance review is the terms of the specific model provider
> each request lands on, not only the aggregator's.

## What this API stores itself

| Data | Stored as | Where | Kept for |
|---|---|---|---|
| Translation cache | `sha256(source, target, text)` → translated text | in-process memory, or your Redis | `CACHE_TTL_SECONDS` (default 1 h), at most `CACHE_MAX_ITEMS` (1000) entries; `CACHE_TTL_SECONDS=0` disables it |
| Chat conversations | `sha256(owner)` + conversation ID → up to 40 messages / 20,000 characters | in-process memory, or your Redis | `CONVERSATION_TTL_SECONDS` (default 24 h of inactivity); the client can delete with `DELETE /v1/chat/{id}` |
| WhatsApp memory | `sha256(phone number)` → preferred language + last 20 messages | in-process memory, or your Redis | `WHATSAPP_MEMORY_TTL_SECONDS` (default 30 days), at most 10,000 users |
| WhatsApp deduplication | message IDs marked "seen" | in-process memory, or your Redis | 24 h (guards against Meta retrying a webhook) |
| Rate-limit counters | API-key fingerprint or IP → request counts | in-process memory, or your Redis | one-minute windows |

- Without `REDIS_URL`, everything is per process and volatile: it is lost on restart and
  not shared between replicas.
- Request bodies are **never written to logs**. Access logs contain the URL path, which
  for the chat endpoints includes the conversation ID.
- API keys are kept only as hashes, never as plaintext (see [SECURITY.md](../SECURITY.md)).

## If your deployment handles sensitive data

Health, government and education deployments often need more than the defaults:

1. **Prefer local providers.** Run [MORENA](MORENA.md) (llama.cpp) and/or Ollama and point
   `TRANSLATION_PROVIDERS` / `LLM_PROVIDERS` only at them; user text then never leaves
   your infrastructure.
2. **Otherwise pick low-retention options:** Cerebras (inputs/outputs not retained),
   Together with Zero Data Retention, OpenAI with ZDR or Modified Abuse Monitoring,
   Hugging Face dedicated endpoints, OpenRouter models labelled as not training on your
   data, and Azure endpoints in a region you control.
3. **Minimize what this API keeps:** `CACHE_TTL_SECONDS=0` if the quota saving isn't
   worth a copy of every text; a shorter `CONVERSATION_TTL_SECONDS`; and stateless
   `/v1/translate` instead of `/v1/chat` when you don't need memory.
4. **Tell your users where their text goes.** The table above is the starting point for
   your own record of processing and for contracts with the providers.

## Keeping this page current

- The statements above were checked on **2026-10-25**. Provider terms change; re-check the
  linked pages before relying on them, and update the dates here when you do.
- **Whenever a PR adds, removes or changes a provider in `config.py`
  (`PROVIDER_PRESETS`), it must update the data-flow diagram and the table in the same
  PR.**
