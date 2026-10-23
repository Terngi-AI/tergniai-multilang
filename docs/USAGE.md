# Using Terngi AI

This guide takes you from zero to a working API, then shows every endpoint with
**curl**, **Python** and **JavaScript** examples.

- [1. Choose a setup](#1-choose-a-setup)
- [2. Run the API](#2-run-the-api)
- [3. Languages](#3-languages)
- [4. Endpoints](#4-endpoints): **chat**, translate, batch, detect, agent
- [5. Errors, limits and auth](#5-errors-limits-and-auth)
- [6. Troubleshooting](#6-troubleshooting)

---

## 1. Choose a setup

You need at least one provider. Pick the row that fits you and put the settings in `.env`
(copy [`.env.example`](../.env.example) first).

| Setup | Cost | What you get | `.env` |
|---|---|---|---|
| **Groq only** | Free tier | Everything, including the agent | `GROQ_API_KEYS=gsk_...` |
| **Groq + MORENA** (recommended) | Free | MORENA translates into African languages locally; Groq handles chat, detection and the agent | `LLM_PROVIDERS=groq,morena`<br>`GROQ_API_KEYS=gsk_...`<br>`TRANSLATION_PROVIDERS=morena,groq` |
| **MORENA only** | Free, no keys | Translation only (no detection, chat is weak, no agent) | `LLM_PROVIDERS=morena`<br>`TRANSLATION_PROVIDERS=morena` |
| **Azure + Groq** | Azure paid tier | Azure translation with LLM fallback | `AZURE_TRANSLATOR_KEYS=...`<br>`GROQ_API_KEYS=gsk_...` |

Get a free Groq key at <https://console.groq.com/keys>. To survive rate limits, add several
keys and models:

```bash
GROQ_API_KEYS=gsk_first,gsk_second
GROQ_MODELS=openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b
```

Other OpenAI-compatible providers work the same way. Add the name to `LLM_PROVIDERS` and set
`<NAME>_API_KEYS` and `<NAME>_MODELS` (built in: `openrouter`, `together`, `cerebras`,
`huggingface`, `openai`, `ollama`). Any other name needs `<NAME>_BASE_URL`.

## 2. Run the API

**Python**

```bash
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements.lock
uvicorn main:app --reload
```

**MORENA** (only for setups that use it), in a second terminal:

```bash
brew install llama.cpp          # or see https://github.com/ggml-org/llama.cpp
llama-server --hf-repo vamboai/morena-1.5b-instruct-gguf \
  --hf-file morena-1.5b-instruct-Q4_K_M.gguf --port 8080 -c 4096
```

**Docker Compose** (API and MORENA together):

```bash
docker compose --profile morena up
```

Check that it's ready:

```bash
curl http://localhost:8000/health/ready
# {"status":"ready","services":{"translator":true,"llm":true,"agent":true}}
```

Interactive docs: <http://localhost:8000/docs>.

## 3. Languages

**96 languages.** `GET /v1/languages` returns the full list.

- **African (27):** Yoruba (`yo`), Hausa (`ha`), Igbo (`ig`), Nigerian Pidgin (`pcm`), Swahili (`sw`), Kinyarwanda (`rw`), Shona (`sn`), isiZulu (`zu`), isiXhosa (`xh`), Setswana (`tn`), Afrikaans (`af`), isiNdebele (`nr`), Amharic (`am`), Somali (`so`), Tigrinya (`ti`), Oromo (`om`), Malagasy (`mg`), Lingala (`ln`), Luganda (`lg`), Chichewa (`ny`), Kirundi (`rn`), Sesotho (`st`), Sesotho sa Leboa (`nso`), Wolof (`wo`), Fula (`ff`), Ewe (`ee`), Twi (`tw`)
- **European (32):** English (`en`), French (`fr`), Spanish (`es`), Portuguese (`pt`), German (`de`), Italian (`it`), Dutch (`nl`), Polish (`pl`), Irish (`ga`), Welsh (`cy`), Swedish (`sv`), Danish (`da`), Norwegian (`nb`), Finnish (`fi`), Icelandic (`is`), Greek (`el`), Czech (`cs`), Slovak (`sk`), Hungarian (`hu`), Romanian (`ro`), Bulgarian (`bg`), Ukrainian (`uk`), Russian (`ru`), Croatian (`hr`), Serbian (`sr-Latn`), Slovenian (`sl`), Lithuanian (`lt`), Latvian (`lv`), Estonian (`et`), Albanian (`sq`), Macedonian (`mk`), Turkish (`tr`)
- **Middle Eastern (6):** Arabic (`ar`), Hebrew (`he`), Persian (`fa`), Urdu (`ur`), Pashto (`ps`), Kurdish (`ku`)
- **Asian (31):** Chinese (Simplified) (`zh-Hans`), Chinese (Traditional) (`zh-Hant`), Cantonese (`yue`), Japanese (`ja`), Korean (`ko`), Hindi (`hi`), Bengali (`bn`), Punjabi (`pa`), Tamil (`ta`), Telugu (`te`), Marathi (`mr`), Gujarati (`gu`), Kannada (`kn`), Malayalam (`ml`), Sinhala (`si`), Nepali (`ne`), Thai (`th`), Lao (`lo`), Khmer (`km`), Burmese (`my`), Vietnamese (`vi`), Indonesian (`id`), Malay (`ms`), Filipino (`fil`), Kazakh (`kk`), Uzbek (`uz`), Azerbaijani (`az`), Georgian (`ka`), Armenian (`hy`), Kyrgyz (`ky`), Turkmen (`tk`)

Which provider handles which language:

| Provider | Languages |
|---|---|
| MORENA | Its 12 African languages (Yoruba to isiNdebele in the list above) plus English and French. Never used for other languages. |
| Azure Translator | All except Nigerian Pidgin, isiNdebele, Oromo, Luganda, Chichewa, Kirundi, Wolof, Fula, Ewe and Twi |
| LLMs (Groq etc.) | All. Quality is best for widely spoken languages; native-speaker feedback is welcome for the rest |

Wherever a request takes `from_language` (or `language` for chat and the agent), you can pass
`"auto"` to detect it.

## 4. Endpoints

All examples assume `BASE=http://localhost:8000`. If the server sets `API_KEYS`, add the
header `X-API-Key: <key>`.

### 💬 Chat: `POST /v1/chat` (start here)

A normal AI chat, like ChatGPT, in any supported language. Ask questions, get advice, write,
study or just talk. The server remembers the conversation, so send only the new message plus
the `conversation_id` from the previous reply.

**In the browser:** open <http://localhost:8000/chat>.

| Field | Default | Meaning |
|---|---|---|
| `message` | required | What you want to say, in any supported language |
| `conversation_id` | none (starts a new chat) | Continue an earlier conversation |
| `language` | `"auto"` | Language of `message` |
| `reply_language` | same as `message` | Language of the reply |

```bash
curl -X POST $BASE/v1/chat -H 'Content-Type: application/json' \
  -d '{"message": "Hi! My name is Chidi and I sell tomatoes in Enugu market."}'
# {"conversation_id": "3f9c…", "reply": "Hello Chidi! … How can I help you today?", "language": "en", ...}

curl -X POST $BASE/v1/chat -H 'Content-Type: application/json' \
  -d '{"message": "Kedu aha m? Gịnị ka m na-ere?", "conversation_id": "3f9c…"}'
# {"reply": "Aha gị bụ Chidi, ị na-ere tomato.", "language": "ig", ...}
```

You can switch languages mid-conversation and it keeps the context.

#### Streaming: `POST /v1/chat/stream`

Same request body, but the reply arrives word by word as
[Server-Sent Events](https://developer.mozilla.org/docs/Web/API/Server-sent_events), so users see
text immediately instead of waiting for the whole answer. The web chat at `/chat` uses this.

| Event | Data | Meaning |
|---|---|---|
| `start` | `{"conversation_id"}` | The conversation this reply belongs to |
| `token` | `{"text"}` | The next piece of the reply; append it |
| `discard` | `{}` | Drop the text streamed so far (the assistant decided to use a tool) |
| `tool` | `{"tool", "ok"}` | A tool the assistant ran, e.g. `translate` |
| `done` | `{"conversation_id", "reply", "language", "reply_language", "steps"}` | Finished. **Show `reply`** in place of the streamed text: for non-English replies the final, checked translation can differ from what streamed |
| `error` | `{"message", "status_code"}` | Something failed after streaming started |

```bash
curl -N -X POST $BASE/v1/chat/stream -H 'Content-Type: application/json' \
  -d '{"message": "Explain in three sentences why the sky is blue."}'
# event: start
# data: {"conversation_id": "9b1d…"}
#
# event: token
# data: {"text": "The sky appears blue because"}
# …
# event: done
# data: {"conversation_id": "9b1d…", "reply": "The sky appears blue because …", ...}
```

Python, reading the stream with `httpx`:

```python
import json, httpx

with httpx.stream("POST", f"{BASE}/v1/chat/stream", json={"message": "Habari!"}, timeout=120) as r:
    event = None
    for line in r.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:])
            if event == "token":
                print(data["text"], end="", flush=True)
            elif event == "done":
                print("\n\nconversation:", data["conversation_id"])
```

Errors that happen before streaming starts (unknown `conversation_id`, unsupported
`reply_language`) are normal JSON errors with a 4xx status.

Other calls:

| Call | Purpose |
|---|---|
| `GET /v1/chat/{conversation_id}` | The conversation so far |
| `DELETE /v1/chat/{conversation_id}` | Forget it |

Conversations are kept for 24 hours after the last message (`CONVERSATION_TTL_SECONDS`), in
server memory or, when `REDIS_URL` is set, in Redis (shared by all replicas and kept across
restarts), and are private to the client that started them (same API key,
or same IP address when no key is used).

### Translate: `POST /v1/translate`

```bash
curl -X POST $BASE/v1/translate -H 'Content-Type: application/json' \
  -d '{"content": "Good morning, how is your family?", "from_language": "en", "to_language": "yo"}'
```

```json
{"translated_text": "Ẹ kú àárọ̀, báwo ni ẹbí yín ṣe wà?", "from_language": "en",
 "to_language": "yo", "original_text": "Good morning, how is your family?"}
```

### Batch translate: `POST /v1/translate/batch`

Up to 25 texts (50,000 characters) in one request; results come back in order.

```bash
curl -X POST $BASE/v1/translate/batch -H 'Content-Type: application/json' \
  -d '{"texts": ["Thank you", "Good night"], "from_language": "en", "to_language": "ha"}'
# {"translations": ["Na gode", "Barka da dare"], "from_language": "en", "to_language": "ha"}
```

### Detect language: `POST /v1/detect`

```bash
curl -X POST $BASE/v1/detect -H 'Content-Type: application/json' \
  -d '{"content": "Wetin you dey do for house?"}'
# {"language": "pcm", "language_name": "Nigerian Pidgin", "score": 0.99, "is_supported": true}
```

### Converse: `POST /v1/converse`

Simple chat: the message is translated to English, answered, and the answer is translated
back. Pass earlier turns in `memory_context`.

```bash
curl -X POST $BASE/v1/converse -H 'Content-Type: application/json' \
  -d '{"content": "Ina kwana?", "from_language": "auto", "to_language": "ha"}'
```

### Agent: `POST /v1/agent`

The same assistant as `/v1/chat`, but stateless: you send the `history` yourself. Useful when
your app stores conversations. It understands any supported language and decides
for itself when to use tools:

| Tool | What it does |
|---|---|
| `translate` | Translates through the provider chain (MORENA, Azure, LLMs) |
| `detect_language` | Identifies a language |
| `list_languages` | Lists supported languages |
| `get_current_time` | Current date and time in any time zone (default `Africa/Lagos`) |

Request fields:

| Field | Default | Meaning |
|---|---|---|
| `message` | required | What the user said, in any supported language |
| `language` | `"auto"` | Language of `message` |
| `reply_language` | same as `language` | Language of the answer |
| `history` | `null` | Earlier turns: `[{"role": "user" \| "assistant", "content": "..."}]` |

```bash
curl -X POST $BASE/v1/agent -H 'Content-Type: application/json' \
  -d '{"message": "How do I say \"thank you very much\" in Swahili, isiZulu and Hausa?"}'
```

```json
{
  "answer": "- Swahili: asante sana\n- isiZulu: Ngiyabonga kakhulu\n- Hausa: na gode sosai",
  "language": "en",
  "reply_language": "en",
  "steps": [
    {"tool": "translate", "arguments": {"text": "thank you very much", "target_language": "sw"},
     "output": {"translation": "asante sana", "source_language": "en", "target_language": "sw"}},
    "..."
  ]
}
```

Ask in Igbo and the answer comes back in Igbo:

```bash
curl -X POST $BASE/v1/agent -H 'Content-Type: application/json' \
  -d '{"message": "Nnọọ! Kedu ụbọchị taa?"}'
# {"answer": "Ụtụtụ ọma! Taa bụ Mọnde, Ọktoba 19, 2026.", "language": "ig", "reply_language": "ig",
#  "steps": [{"tool": "get_current_time", ...}, {"tool": "translate", ...}]}
```

Ask in English and get the answer in Hausa:

```bash
curl -X POST $BASE/v1/agent -H 'Content-Type: application/json' \
  -d '{"message": "Give me two tips for staying healthy during harmattan.", "reply_language": "ha"}'
```

`steps` shows exactly which tools ran and what they returned, which helps with debugging
and building UIs. See [AGENT.md](AGENT.md) for how it works and how to add tools.

### 📱 WhatsApp bot: `/v1/whatsapp/*`

Connect a WhatsApp Business number and people can chat with Terngi AI there, in their own
language. `POST /v1/whatsapp/send` sends messages (translated if you like). Setup and
details: [WHATSAPP.md](WHATSAPP.md).

### Python client

```python
import httpx

BASE = "http://localhost:8000"
HEADERS = {}  # {"X-API-Key": "..."} if the server requires it

with httpx.Client(base_url=BASE, headers=HEADERS, timeout=60) as api:
    r = api.post(
        "/v1/translate",
        json={
            "content": "Welcome to our school.",
            "from_language": "en",
            "to_language": "ig",
        },
    )
    r.raise_for_status()
    print(r.json()["translated_text"])

    # A chat: the server remembers the conversation
    conversation_id = None
    for message in ["Ẹ káàrọ̀! Orúkọ mi ni Adé.", "Kí ni orúkọ mi?"]:
        body = {"message": message}
        if conversation_id:
            body["conversation_id"] = conversation_id
        r = api.post("/v1/chat", json=body)
        r.raise_for_status()
        conversation_id = r.json()["conversation_id"]
        print(r.json()["reply"])
```

### JavaScript (browser or Node 18+)

```js
const BASE = "http://localhost:8000";

let conversationId = null;

async function chat(message) {
  const res = await fetch(`${BASE}/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" /*, "X-API-Key": "..." */ },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.message);
  conversationId = body.conversation_id;
  return body.reply;
}

console.log(await chat("Habari! What should I pack for a trip to Kigali?"));
console.log(await chat("And what's the weather usually like in December?"));
```

To call the API from a web page on another origin, set `CORS_ORIGINS` on the server.

## 5. Errors, limits and auth

Every error has the same shape:

```json
{"error": true, "message": "Target language 'de' not supported. ...", "status_code": 400}
```

| Status | Meaning |
|---|---|
| `400` | Unsupported language, or batch too large |
| `401` | Missing or invalid `X-API-Key` (only when `API_KEYS` is set) |
| `404` | Unknown or expired `conversation_id` |
| `422` | Invalid request body (details in `details`) |
| `429` | Rate limit exceeded; wait `Retry-After` seconds |
| `502` | Every configured provider failed |
| `503` | No provider is configured for this task |

Every response carries `X-Request-ID` (send your own to trace a request) and
`X-RateLimit-Remaining`.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `503 ... not configured` | Add a provider key, or check `GET /health/ready` |
| `502` on translation | Look at the server log: it names the provider and status that failed |
| Logs show `key …abcd was rejected` | That key is revoked or wrong; it's skipped for an hour |
| Logs show `rate-limited` | Normal on free tiers. Requests move to the next key or model, and wait up to `RATE_LIMIT_MAX_WAIT_SECONDS` (10s) when all are busy. Add more keys or a second provider to avoid waits |
| MORENA requests fail | Check `curl localhost:8080/health`; translation falls back to the next provider meanwhile |
| Chat returns `503 Conversation storage is unavailable` | Redis is unreachable; check `REDIS_URL` and `GET /health/ready` (`"storage": false`). Translation keeps working without the cache |
| Agent returns `503` | The agent needs an OpenAI-compatible provider (e.g. Groq); MORENA alone can't run it |
