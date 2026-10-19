# Running MORENA (free, local African-language model)

[MORENA](https://huggingface.co/vamboai/morena-1.5b-instruct) is a 1.5B-parameter model trained
from scratch for twelve African languages, including **Hausa, Yoruba, Igbo and Nigerian Pidgin**,
plus English and French. It was built by Isheanesu Misi at [Vambo AI](https://huggingface.co/vamboai)
and released under the **Apache 2.0** license, so commercial use is allowed.

All twelve of its African languages are supported by Terngi AI. With MORENA configured, the
[agent](AGENT.md) writes its answers in those languages through MORENA.

Terngi AI can use it for translation (and chat) through a [llama.cpp](https://github.com/ggml-org/llama.cpp)
server. It costs nothing to run: the 4-bit build is 0.9 GB and runs on an ordinary laptop CPU.

## What it is good at

| | Notes from the [model card](https://huggingface.co/vamboai/morena-1.5b-instruct) |
|---|---|
| ✅ English → African translation | 45.8 chrF++ on FLORES+, ahead of MADLAD-400-3B (37.8) and Lugha-Llama-8B (36.8) |
| ⚠️ African → English translation | 48.7 chrF++, behind MADLAD-400-3B (53.6) |
| ⚠️ General chat | Small model; refuses many harmless requests (41% of benign prompts not answered well) |
| ⚠️ Evaluation | All scores are model-judged; no native-speaker ratings yet |

**Recommended setup:** use MORENA first for translation and keep a larger model (e.g. Groq) for
chat, detection and as a translation fallback:

```bash
LLM_PROVIDERS=groq,morena
TRANSLATION_PROVIDERS=morena,groq
CHAT_PROVIDERS=groq
```

## Option 1: Docker Compose

```bash
cp .env.example .env          # set LLM_PROVIDERS etc. as above
docker compose --profile morena up
```

The `morena` service downloads `morena-1.5b-instruct-Q4_K_M.gguf` from Hugging Face on first
start and serves it on port 8080. The API container reaches it at `http://morena:8080`.

## Option 2: llama.cpp directly

```bash
# macOS: brew install llama.cpp   (other platforms: see the llama.cpp README)
llama-server \
  --hf-repo vamboai/morena-1.5b-instruct-gguf \
  --hf-file morena-1.5b-instruct-Q4_K_M.gguf \
  --port 8080 -c 4096
```

Then set `MORENA_BASE_URL=http://localhost:8080` and add `morena` to `LLM_PROVIDERS`.

## Free hosting options

- **Your own machine or any small VPS:** 2 GB of RAM is enough for the Q4 build.
- **Hugging Face Spaces (free CPU tier):** run the llama.cpp server image in a Docker Space and
  point `MORENA_BASE_URL` at it. Free Spaces sleep when idle, so keep a fallback provider configured.
- No hosted inference API offers MORENA yet, so self-hosting is the only option today.

## Prompt format (for contributors)

MORENA uses its own chat markers, which are single reserved tokens: `<reserved_0>` starts a
user turn and `<reserved_1>` starts an assistant turn. Terngi AI calls llama.cpp's `/completion`
endpoint with a prompt built by `services/llm.py::render_morena_prompt`. **Do not** use
`<|user|>`-style markers or the OpenAI chat endpoint; the model card warns this produces
degenerate output.

## Measured locally

On an Apple M4 laptop (Q4_K_M, CPU and Metal via Homebrew llama.cpp), short translations take
0.1–0.4 seconds:

| Input | Output |
|---|---|
| en → yo: *The market opens at eight in the morning.* | Ọ́jà ń ṣí ní agogo mẹ́jọ òwúrọ̀. |
| en → ha: *Thank you for your help.* | Na gode da taimakonka. |
| en → pcm: *Where are you going?* | You dey go where? |

Native-speaker review of more examples is very welcome. See issue #14.
