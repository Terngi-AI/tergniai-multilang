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
