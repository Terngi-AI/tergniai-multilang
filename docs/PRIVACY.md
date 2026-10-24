# Privacy and data protection

This page describes what Terngi AI stores, for how long, and how a caller can access or
erase their own data. It is written to support requests under the Nigeria Data Protection
Act 2023, the GDPR and similar laws; it is not legal advice.

## What is stored

### Chat conversations

`POST /v1/chat` and `POST /v1/chat/stream` keep the conversation on the server so later
turns have context. Each conversation stores:

- the messages you send and the assistant replies
- a random conversation id
- a SHA-256 hash of the owner (the API-key fingerprint, or the client IP when no API key is
  configured)

Conversations are keyed by that owner hash, so one caller can never read or delete another
caller's conversation. The raw API key and the IP address are not stored in the conversation.

### WhatsApp

The bot stores a hash of the phone number, the chosen language and the current conversation
id. Phone numbers are not stored in clear text. See [WHATSAPP.md](WHATSAPP.md).

### Feedback

Translation feedback is stored **only when the request sets `"consent": true`**. It contains
the rated texts, language codes, the provider name, the rating, an optional correction and a
timestamp. Accepted feedback may be published as part of the open evaluation set. See
[FEEDBACK.md](FEEDBACK.md).

### Logs, metrics and rate limits

- Request logs contain method, route, status, timing and request id, not message text.
- Prometheus metrics contain route templates and outcomes, not message text or API keys.
- Rate-limit counters are keyed by a hash of the API key (or the IP address) and expire after
  the rate-limit window.
- Upstream providers receive the text needed to answer a request under their own privacy
  terms. Do not send personal or sensitive text if that is not acceptable to you.

## Retention

| Data | Default retention | Setting |
| --- | --- | --- |
| Chat conversations | 24 hours after the last message | `CONVERSATION_TTL_SECONDS` |
| Maximum stored conversations | 10,000, least recently used evicted first | `CONVERSATION_MAX_ITEMS` |
| WhatsApp user state | 30 days | `WHATSAPP_MEMORY_TTL_SECONDS` |
| Translation cache | 1 hour | `CACHE_TTL_SECONDS` |
| Feedback | Until the operator removes it (append-only) | `FEEDBACK_FILE` / Redis |

In-memory storage is per process and is lost on restart. With `REDIS_URL` set, the same data
is shared by every replica and survives restarts, subject to the TTLs above.

## Access and export

`GET /v1/chat/{conversation_id}` returns a conversation as JSON.
`GET /v1/chat/{conversation_id}/export` returns the same messages with a
`Content-Disposition` header so a browser downloads them as a file. Both endpoints return
`404` for a conversation that does not exist, has expired, or belongs to another caller.

## Deletion

- `DELETE /v1/chat/{conversation_id}` deletes one conversation; it works for any caller
  that owns the conversation (API-key fingerprint or IP address).
- `DELETE /v1/chat` deletes every conversation belonging to the caller. To keep one person
  behind a shared IP (an office, a school, a NAT) from erasing everyone else's chats, this
  endpoint is **only allowed when the request is authenticated with a valid API key**; it
  returns `403` otherwise. Delete individual conversations by id in deployments without API
  keys.
- The `/chat` page has a **Delete my chats** button in Settings. It only works when the
  server has API keys and you entered yours in Settings; otherwise it explains that
  delete-all needs a key.

Ownership is the same API-key fingerprint (or IP address) that created the conversation, so
these endpoints can only delete the caller's own data.

`DELETE /v1/chat` removes conversations from the active store. It does not rewrite Redis
backups or snapshots, and when several replicas use in-memory storage without Redis, each
replica only deletes the conversations it holds. Use Redis for a deployment where a single
delete request must cover every replica. Feedback is append-only by design; an operator who
needs to erase a feedback record must remove it from `FEEDBACK_FILE` or the Redis list.

## Contact

For a data-protection request that the API cannot satisfy, open an issue at
<https://github.com/Terngi-AI/tergniai-multilang/issues>.
