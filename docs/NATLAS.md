# N-ATLaS: replies written natively in Hausa, Igbo and Yoruba

[N-ATLaS](https://huggingface.co/NCAIR1/N-ATLaS) is an open multilingual language model released by
Nigeria's NCAIR with Awarri: a Llama-3 8B fine-tune for **English, Hausa, Igbo and Yoruba**.

By default `/v1/converse` translates the user's message to English, asks an English model, and
translates the answer back. Each translation loses some nuance and cultural context. With N-ATLaS
as a *native chat provider*, a conversation between languages it speaks is answered directly in the
user's language, with no round trip through English.

## Before you use it

- **The model is gated, and its license limits who can use it.** Its
  [Hugging Face page](https://huggingface.co/NCAIR1/N-ATLaS) asks for a login and approved access. As of
  2026-11-05 it is under the "Open-Source Research and Innovation License":
  - Free for research and non-commercial use, **up to 1,000 active users in 30 days**.
  - Commercial use needs a separate license from Awarri and the Federal Ministry.
  - Attribution is required ("Powered by Awarri" on renamed versions).
  - Some uses are prohibited, such as surveillance and disinformation.

  Anyone can deploy this project, so you are the one who has to comply. The terms can change: read the
  current license and acceptable-use terms on the model page before you serve it, and check the context
  length its card gives.
- **You host it.** There is no hosted default: you give Terngi AI the address of a server that runs it.
  An 8B model needs a GPU with enough memory, or a quantised build.
- **Quality has not been measured.** Nothing here compares its answers with the translation pipeline's
  yet. That needs the evaluation set and harness from [#14](https://github.com/Terngi-AI/tergniai-multilang/issues/14)
  and [#26](https://github.com/Terngi-AI/tergniai-multilang/issues/26). Try it on your own language
  pairs before you make it the default.

## Set it up

Serve the model with anything that speaks the OpenAI chat completions API (vLLM, Hugging Face TGI, or a
Hugging Face Inference Endpoint), then:

```bash
LLM_PROVIDERS=groq,natlas
NATLAS_BASE_URL=http://localhost:8000/v1
NATLAS_MODEL=NCAIR1/N-ATLaS      # the name your server serves the model under
# NATLAS_API_KEY=...             # only if your server asks for one
NATIVE_CHAT_PROVIDERS=natlas     # answer natively, for the languages it lists
```

`natlas` is a built-in provider name. It is limited to `en`, `ha`, `ig` and `yo`; narrow that with
`NATLAS_LANGUAGES=yo,ha`.

Without `NATIVE_CHAT_PROVIDERS`, nothing changes: N-ATLaS is just another LLM provider.

## How a conversation goes

| Conversation | What happens |
|---|---|
| Both languages are among the native provider's, for example Yoruba to Yoruba, or Hausa to Igbo | The provider is asked once, and told to reply in the target language. Its reply is returned as it is. |
| Either language is outside its list (French, say) | The usual flow: translate to English, ask the English model, translate back. |
| The native provider fails or is resting | The usual flow runs, so the request still gets an answer. |

The `translated_text` field is still the user's message translated into the target language, so one
translation call is made and the translation providers are still needed. The reply is never translated.

A provider with no language list means "any language", which is not a promise to speak this one, so it
is never treated as native: list its languages with `<NAME>_LANGUAGES`.

## Other things it will do

Because N-ATLaS is an LLM provider, it also joins the default chat and translation chains for the
languages it lists, after the providers before it in `LLM_PROVIDERS`. To keep it out of them, set
`CHAT_PROVIDERS` and `TRANSLATION_PROVIDERS` yourself, for example `CHAT_PROVIDERS=groq` and
`TRANSLATION_PROVIDERS=azure,groq`.

## Your users' data

User text goes to the server at `NATLAS_BASE_URL`. If you serve the model yourself it stays on your
network. If you point it at a hosted endpoint, that host's terms apply. See [DATA.md](DATA.md).
