# The Terngi AI agent

The assistant behind `POST /v1/chat` (with server memory) and `POST /v1/agent` (stateless) is a
general conversational AI that can talk about anything. Under the hood it is an agent: a tool-calling language model that reasons in
English and uses tools to translate, detect languages and look things up. Usage examples are in
[USAGE.md](USAGE.md#agent-post-v1agent); this page explains how it works.

## How a request flows

```
user message (any language)
   │
   ├─ 1. detect the language (if "auto")
   ├─ 2. translate the message to English (provider chain: Azure / MORENA / LLM)
   │
   ├─ 3. loop, at most AGENT_MAX_STEPS times:
   │      model (AGENT_PROVIDERS) ──► answer?  ──► go to 4
   │                              └─► tool calls ──► run tools ──► results back to model
   │
   └─ 4. make sure the answer is in reply_language
          (use the agent's own translation, or translate it if the agent didn't)
```

- **The model thinks in English.** Large models reason best in English, so the server gives the
  model the original message plus an English translation.
- **Specialised models write the African-language text.** The system prompt tells the agent to
  write its answer in English and call `translate`. Translation then goes through
  `TRANSLATION_PROVIDERS`, so with MORENA configured the final Yoruba, Hausa or isiZulu text
  comes from a model trained for those languages.
- **The server checks the result.** Models sometimes echo the English draft or skip the tool, and
  `_finalise_answer` in `services/agent.py` fixes both cases.

## Streaming

`POST /v1/chat/stream` runs the same loop with streamed model calls. Text from each model
step is forwarded as `token` events as it arrives. If a step turns out to be a tool call, a
`discard` event tells the client to drop that text, and each tool that runs is reported as a
`tool` event. The final `done` event carries the checked answer. Provider fallback still works
until the first token has been sent; after that a failure ends the stream with an `error`
event, so a reply never mixes text from two models.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_PROVIDERS` | OpenAI-compatible providers in `CHAT_PROVIDERS` | Models that run the agent; they must support tool calling |
| `AGENT_MAX_STEPS` | `6` | Maximum model turns before the agent must answer |

The agent gets the same multi-key, multi-model fallback as everything else. MORENA can't drive
the agent: its model card notes it rarely decides to call tools by itself. It still serves the
agent's translations.

## Safety limits

- At most `AGENT_MAX_STEPS` model turns and 8 tool calls per turn
- Tool arguments are validated: unknown tools, bad JSON, unsupported languages and oversized
  text become error results the model can see and recover from, never server errors
- Tools only read data or call the translation chain; none of them change state
- `history` only accepts `user` and `assistant` turns, so callers can't inject system prompts

## What the assistant will and won't do

Every chat (`/v1/chat`, `/v1/agent`, the WhatsApp bot) and `/v1/converse` system prompt
carries the same honesty rules (#145), written once in English. The answer stays in the
user's language.

- **It says when it doesn't know.** It doesn't present guesses as facts.
- **It doesn't invent details:** facts, sources, statistics, quotes, links, phone numbers,
  addresses, prices, dates or opening hours. When it wasn't given a detail, it says so and
  suggests where to check. To let it answer such questions, give it the facts (for the
  WhatsApp bot, `WHATSAPP_CONTEXT`).
- **Health, medicines, legal matters, immigration, benefits and money:** general information
  only, never a diagnosis, a dose or a ruling on someone's own case. It suggests a doctor,
  nurse, pharmacist, lawyer or advice service, or the official source.
- **Emergencies come first.** If someone is badly hurt, not breathing, in danger or thinking
  of harming themselves, it first tells them to follow `EMERGENCY_ADVICE`, then helps briefly.
  The default is generic ("contact your local emergency services or go to the nearest
  hospital or clinic right away"); set it to your country's number, for example
  `EMERGENCY_ADVICE="call 112 or go to the nearest hospital right away"`.

These are instructions to a language model, not guarantees: models still make mistakes,
especially in languages with little training data. `eval/honesty/cases.jsonl` has questions
with no safe confident answer (invented phone numbers, doses for a child, emergencies) that
the weekly **Injection eval** workflow runs against a real deployment, so you can see how a
model or prompt change affects them.

## Moderation (optional)

`POST /v1/chat`, `POST /v1/chat/stream`, `POST /v1/agent` and `POST /v1/converse` can screen
user messages with Meta's Llama Prompt Guard before they reach the chat model:

| Variable | Default | Meaning |
|---|---|---|
| `MODERATION_PROVIDERS` | empty (disabled) | LLM providers that serve Prompt Guard, e.g. `groq` |
| `PROMPT_GUARD_MODEL` | `meta-llama/llama-prompt-guard-2-86m` | The classifier model served by those providers |
| `MODERATION_FAIL_MODE` | `open` | Classifier unreachable: `open` lets the request through, `closed` refuses it with `503` |
| `MODERATION_CHUNK_CHARS` | `1000` | Longer texts are split into overlapping chunks of this size, classified concurrently |
| `MODERATION_MAX_CHUNKS` | `12` | Most chunks per check; more counts as a classifier failure, so `MODERATION_FAIL_MODE` decides |

When moderation is enabled:

- The user's own message **and its English translation** are classified before the chat
  model is called (#168). Prompt Guard is weaker on many local languages, and the English
  rendering is what the model reads most clearly, so either one being flagged is enough. A
  flagged message is answered with a polite refusal translated into the user's language.
- Prompt Guard 2 reads only 512 tokens, so texts longer than `MODERATION_CHUNK_CHARS` are
  classified in overlapping chunks; an injection hidden after long padding is still seen.
- In `/v1/converse`, the client-supplied `memory_context` is classified too (joined into one
  text), and the model is told those turns may not be genuine (#169). Set
  `CONVERSE_ALLOW_ASSISTANT_HISTORY=false` to reject client-written assistant turns when
  your integration relays text from untrusted end users.
- Tool calls that would echo user-supplied text into the context (`translate`,
  `detect_language`) are classified too, so an injection hidden in a tool argument never
  reaches the model; the tool result is replaced with a blocked notice.
- Flagged events are logged without the message text and counted in
  `terngi_moderation_flagged_total` (label `kind` = `user_message`, `translation`, `history` or `tool_result`).
- When moderation is disabled there is no extra latency and no extra upstream call.

Prompt Guard is a small classifier; it runs on the same providers as the chat model, so it
shares their keys, models (the classifier must be listed in the provider's `MODELS`) and
rate limits.

## Adding a tool

1. Write an async function in `services/agent.py` that takes the arguments dict and returns a
   JSON-serialisable dict. Raise `ValueError` for bad input; the message is shown to the model.
2. Register it in `TOOLS`.
3. Describe it in `tool_definitions()` (OpenAI function-calling JSON schema). A clear
   description is what makes the model use the tool well.
4. Mention it in the system prompt if the model should prefer it for certain requests.
5. Add tests in `tests/test_agent.py`. Mock the model with `respx` returning a `tool_calls`
   message, as the existing tests do.

Ideas for new tools are tracked under the
[`african-models`](https://github.com/Terngi-AI/tergniai-multilang/labels/african-models) label,
e.g. text-to-speech (#25) and tone-mark restoration (#27).
