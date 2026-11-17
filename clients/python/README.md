# Terngi AI Python SDK

A small typed client for the [Terngi AI](https://github.com/Terngi-AI/tergniai-multilang) API:
chat (with memory and streaming), translation, language detection and the agent.

## Install

```bash
pip install ./clients/python      # from a clone of the repository
```

Requires Python 3.10+, `httpx` and `pydantic` v2.

## Use

```python
from terngi import TerngiClient

with TerngiClient(base_url="http://localhost:8000", api_key=None) as client:
    reply = client.chat("Sannu! Yaya kake?")
    print(reply.reply)

    # Continue the same conversation; the server remembers it
    follow_up = client.chat("What did I just say?", conversation_id=reply.conversation_id)

    # Stream the reply as it is generated
    for event in client.chat_stream("Tell me a short story"):
        if event.event == "token":
            print(event.data["text"], end="")

    print(client.translate("Good morning", to_language="ig").translated_text)
    print(client.detect("Habari yako?").language)  # "sw"
```

| Method | Endpoint |
|---|---|
| `chat(message, conversation_id=None, language="auto", reply_language=None)` | `POST /v1/chat` |
| `chat_stream(...)` → iterator of `StreamEvent` | `POST /v1/chat/stream` |
| `get_conversation(id)`, `delete_conversation(id)` | `GET` / `DELETE /v1/chat/{id}` |
| `translate(content, to_language, from_language="auto")` | `POST /v1/translate` |
| `translate_batch(texts, to_language, from_language="auto")` | `POST /v1/translate/batch` |
| `detect(content)` | `POST /v1/detect` |
| `agent(message, language="auto", reply_language=None, history=None)` | `POST /v1/agent` |
| `languages()` | `GET /v1/languages` |

## Errors

| Exception | When |
|---|---|
| `AuthenticationError` | `401`: missing or invalid API key |
| `RateLimitError` | `429`: wait `retry_after` seconds |
| `APIResponseError` | Any other error status; has `status_code` and `message` |

All of them inherit from `TerngiError`.

See [`examples/quickstart.py`](examples/quickstart.py) and the API guide in
[`docs/USAGE.md`](../../docs/USAGE.md).
