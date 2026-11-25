# Dataset card: Terngi native-speaker evaluation set

> Part of [#14](https://github.com/Terngi-AI/tergniai-multilang/issues/14). Scored by
> [`scripts/eval_translation.py`](../../scripts/eval_translation.py).

- **Version / date**: 0.1, 2026-11-25. English sources only; references are being collected.
- **Owner**: the Terngi AI maintainers.
- **Purpose**: evaluation only. Measures translation quality through the API, in both
  directions, so prompt, model and provider changes can be compared. Never used for training,
  so the scores stay honest.

## Sources and licences

| Source | URL | Licence | Redistribution allowed? | Notes |
|---|---|---|---|---|
| English source sentences, written for this project | this folder | CC BY 4.0 | yes | Original sentences, not copied from any website or dataset |
| Reference translations by contributors | this folder | CC BY 4.0 | yes | Each contributor agrees to this licence in their pull request |

## Contents

- **`sources.jsonl`**: 80 short English sentences, 8 in each of 10 everyday domains:
  greetings, health, emergency, money, government, education, farming, transport, daily life
  and work. Some contain numbers, dates, times and amounts on purpose, since changing them is
  the most harmful translation error (see #144).
- **`languages.json`**: the languages we want references for. `supported` languages are
  scored through the API. `collecting` languages (Tiv, Efik, Kanuri, Ibibio) aren't supported
  by any provider in Terngi yet; their references are collected now so a future provider
  (#23, #13) can be measured from day one.
- **`references/<code>.jsonl`**: one line per translated sentence:

  ```json
  {"id": "health-01", "text": "…", "translator": "github-handle", "reviewed": false, "reviewed_by": null}
  ```

  `id` must match a source. A reference counts only once a **second** native speaker has
  checked it and set `"reviewed": true` and `"reviewed_by"`.

## Collection and consent

- Written and reviewed by volunteer native speakers through pull requests. No user data is
  involved: contributors translate the fixed sentences in `sources.jsonl`.
- **Consent and licence**: by opening a pull request that adds references, the contributor
  confirms the translations are their own work and licenses them under CC BY 4.0. Their
  GitHub handle is recorded as `translator` (optional; leave it out to stay anonymous).
- **Withdrawal**: a contributor can ask for their rows to be removed by opening an issue; rows
  are found by `translator`.
- **PII**: the sentences contain no personal data. `tests/test_translation_eval.py` runs
  every source and reference through `services/pii.py` and fails if anything is flagged.

## Known limitations and biases

- 80 sentences is small: good for spotting regressions and big gaps between providers, not
  for fine-grained ranking. Differences of 1–2 chrF++ points are noise.
- The sources are written in English first, so they carry English sentence structure
  ("translationese"). The `x-en` direction uses human references as input, which helps a
  little.
- One reference per sentence: a correct translation worded differently scores lower. Dialect
  matters too (Ọ̀yọ́ against Èkìtì Yoruba, Kano against Sokoto Hausa); contributors note their
  dialect in the PR.
- Domains lean towards public-service use (health, government, education), which is what this
  API is mostly used for.

## How to contribute references

1. Pick a language in `languages.json` (or propose a new one in an issue) and comment on #14
   so two people don't translate the same sentences.
2. Translate any number of sentences into `references/<code>.jsonl`, using the format above
   with `"reviewed": false`. Translate the meaning naturally, the way you would say it to a
   neighbour; keep numbers, dates and amounts exactly.
3. Use the language's proper spelling, **including tone marks and diacritics** (ẹ, ọ, ṣ, ɗ,
   ƙ, ụ and so on).
4. Open a pull request. Another native speaker reviews it and sets `"reviewed": true` and
   `"reviewed_by"`. Please don't review your own lines, and **don't use machine translation**:
   a reference made by a machine rewards the machines that think alike.

## Splits

Everything is a test set. No row may be used for training or fine-tuning (see #96); a
training pipeline must exclude every `id` in `sources.jsonl`.

## Contact

Questions or removal requests: open an issue in this repository, or report privately through
GitHub (see `SECURITY.md`).
