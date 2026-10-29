# WhatsApp bot

Terngi AI can answer people on WhatsApp. They message your WhatsApp number in any supported
language and get answers in that language, with the conversation remembered. It works for
any use: a business answering customers, a clinic, a school, a community group, a tourism
service, or a personal assistant.

It uses the [WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api) from
Meta and the same agent as `/v1/chat`, so it detects languages, uses tools and translates.

## How it works

```
Person ──WhatsApp──▶ Meta ──webhook──▶ POST /v1/whatsapp/webhook ──▶ agent ──▶ reply via Meta
```

- Meta sends each message to the webhook, signed with your app secret. Unsigned or wrongly
  signed requests are rejected, so the webhook needs no API key
- The bot answers in the background, so Meta gets its `200` at once; messages Meta sends
  twice are answered once
- Each person's language and conversation are remembered (in memory, or in Redis with
  `REDIS_URL`) for `WHATSAPP_MEMORY_TTL_SECONDS` (30 days by default). Phone numbers are
  stored only as keyed hashes (HMAC-SHA256 under `HASH_SECRET`), so a leaked store cannot
  be turned back into phone numbers

## Set up

1. **Meta app.** In [Meta for Developers](https://developers.facebook.com/), create a
   Business app, add the **WhatsApp** product and a phone number (Meta gives you a test
   number to start). Note the **phone number ID**, create a **permanent access token**
   (Business settings → System users) and copy the **app secret** (App settings → Basic)
2. **Configure Terngi AI** (`.env`):

   ```bash
   # Keying secret for personal identifiers (required; the app refuses to start
   # without it). Generate one: python -c "import secrets; print(secrets.token_hex(32))"
   HASH_SECRET=<64-char-random-hex>
   WHATSAPP_PHONE_NUMBER_ID=1234567890
   WHATSAPP_ACCESS_TOKEN=EAAG...
   WHATSAPP_APP_SECRET=...
   WHATSAPP_VERIFY_TOKEN=any-long-random-string
   # Optional: facts the bot answers from, and a greeting for first-time users
   WHATSAPP_CONTEXT="Ade's Kitchen: open 9am-9pm Monday to Saturday, 12 High Street. Delivery within 3 miles."
   WHATSAPP_WELCOME="Welcome to Ade's Kitchen!"
   ```

   The bot needs an LLM provider that supports tool calling (`AGENT_PROVIDERS`, e.g. Groq)
3. **Public HTTPS address.** Meta must reach your API over HTTPS. In production, use your
   domain; for local testing, a tunnel such as `ngrok http 8000`
4. **Webhook.** In the app dashboard (WhatsApp → Configuration), set the callback URL to
   `https://your-domain/v1/whatsapp/webhook` and the verify token to `WHATSAPP_VERIFY_TOKEN`,
   then subscribe to the **messages** field
5. Send your number a message, for example "Báwo ni?" or "When are you open?"

## What people can send

| Message | Effect |
|---|---|
| Anything | An answer in the language they wrote in (remembered from their first message) |
| `LANGUAGE Yoruba` or `LANGUAGE yo` | Change their language |
| `RESET` | Start a new conversation |
| `HELP` | List the commands |

Command words stay in English inside translated replies, so people always see what to type.

## Sending messages

Your own systems can send messages through the API (this endpoint needs your `X-API-Key`):

```bash
# Text, translated into the recipient's language first
curl -X POST http://localhost:8000/v1/whatsapp/send -H 'Content-Type: application/json' \
  -H "X-API-Key: $KEY" \
  -d '{"to": "+447700900123", "text": "Your order is ready.", "to_language": "yo"}'

# An approved template
curl -X POST http://localhost:8000/v1/whatsapp/send -H 'Content-Type: application/json' \
  -H "X-API-Key: $KEY" \
  -d '{"to": "+447700900123", "template": {"name": "order_ready", "language": "en_GB", "parameters": ["A-102"]}}'
```

WhatsApp's rules apply:

- **24-hour window**: free text only reaches people who messaged you in the last 24 hours.
  To message anyone else, use a **template** approved in Meta's dashboard
- **Consent**: only message people who agreed to hear from you, and stop when they ask
- **Pricing**: Meta charges per conversation; check current prices for your countries

## Settings

| Variable | Default | Description |
|---|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | — | Your WhatsApp number's ID |
| `WHATSAPP_ACCESS_TOKEN` | — | A permanent access token |
| `WHATSAPP_APP_SECRET` | — | Verifies webhook signatures |
| `WHATSAPP_VERIFY_TOKEN` | — | Any random string, also set in Meta's dashboard |
| `WHATSAPP_CONTEXT` | — | Facts the bot answers from |
| `WHATSAPP_WELCOME` | — | Sent with the first reply to someone new |
| `WHATSAPP_GRAPH_URL` | `https://graph.facebook.com/v23.0` | Graph API base (change the version as Meta updates it) |
| `WHATSAPP_MEMORY_TTL_SECONDS` | `2592000` (30 days) | How long each person's language and conversation are kept |
| `WHATSAPP_MAX_USERS` | `10000` | People remembered in memory mode (Redis has no limit) |

All four of the first settings are needed; until then the WhatsApp endpoints return `503`.

## Privacy

Messages pass through Meta and your LLM and translation providers. Conversations are kept
for up to `WHATSAPP_MEMORY_TTL_SECONDS`; phone numbers are stored only as keyed hashes
(HMAC-SHA256 under `HASH_SECRET`), and the app refuses to start without it. Changing
`HASH_SECRET` makes previously stored keys unrecoverable, i.e. existing WhatsApp memory
and conversations are forgotten, which is acceptable because they expire on their own. If
you handle personal data (health, finance), tell people how it is used and check your
providers' data terms.
