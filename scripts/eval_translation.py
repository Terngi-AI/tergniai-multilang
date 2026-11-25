#!/usr/bin/env python3
"""
Translation-quality evaluation on the native-speaker set (#14)

Sends the English source sentences in data/terngi-eval/sources.jsonl, and the native-speaker
references in data/terngi-eval/references/<language>.jsonl, through a running Terngi API and
scores the translations with chrF++ in both directions:

- en-x: English source -> language x, scored against the reference
- x-en: the reference -> English, scored against the English source

Only reviewed references are used unless --include-unreviewed is given. Languages the API
doesn't support yet (collected ahead of a provider, e.g. Tiv or Efik) are listed as skipped.

chrF++ (character 6-grams plus word 1-2-grams, beta 2) is computed here, matching
sacrebleu's CHRF(word_order=2) corpus score, so no extra dependency is needed. BLEU is left
out on purpose: it is unreliable for tonal and morphologically rich languages.

Usage:
    EVAL_API_KEY=... python scripts/eval_translation.py --base-url https://staging.example \\
        --languages yo,ha,ig --output translation-report.json
"""

import argparse
import json
import os
import string
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "terngi-eval"
BATCH_SIZE = 25  # MAX_BATCH_SIZE's default

# --- chrF++ ---------------------------------------------------------------------

CHAR_ORDER, WORD_ORDER, BETA = 6, 2, 2
_PUNCTUATION = set(string.punctuation)


def _words(sentence: str) -> List[str]:
    """Split on whitespace and separate one leading or trailing punctuation mark (as sacrebleu)"""
    tokens: List[str] = []
    for word in sentence.split():
        if len(word) == 1:
            tokens.append(word)
        elif word[-1] in _PUNCTUATION:
            tokens += [word[:-1], word[-1]]
        elif word[0] in _PUNCTUATION:
            tokens += [word[0], word[1:]]
        else:
            tokens.append(word)
    return tokens


def _ngrams(items: Sequence[str], n: int) -> Counter:
    return Counter(tuple(items[i : i + n]) for i in range(len(items) - n + 1))


def chrf_statistics(hypothesis: str, reference: str) -> List[int]:
    """[hyp, ref, match] counts for each order: char 1-6, then word 1-2"""
    stats: List[int] = []
    characters_h = list("".join(hypothesis.split()))
    characters_r = list("".join(reference.split()))
    words_h, words_r = _words(hypothesis), _words(reference)
    orders = [(characters_h, characters_r, n) for n in range(1, CHAR_ORDER + 1)]
    orders += [(words_h, words_r, n) for n in range(1, WORD_ORDER + 1)]
    for hyp_items, ref_items, n in orders:
        hyp, ref = _ngrams(hyp_items, n), _ngrams(ref_items, n)
        match = sum(min(count, ref[gram]) for gram, count in hyp.items())
        stats += [sum(hyp.values()), sum(ref.values()), match]
    return stats


def chrf_from_statistics(stats: Sequence[int]) -> float:
    """Corpus chrF++ (0-100) from summed statistics"""
    factor = BETA**2
    total_precision = total_recall = 0.0
    effective_order = 0
    for i in range(CHAR_ORDER + WORD_ORDER):
        n_hyp, n_ref, n_match = stats[3 * i : 3 * i + 3]
        if n_hyp > 0 and n_ref > 0:
            total_precision += n_match / n_hyp
            total_recall += n_match / n_ref
            effective_order += 1
    if not effective_order:
        return 0.0
    precision = total_precision / effective_order
    recall = total_recall / effective_order
    if precision + recall == 0:
        return 0.0
    return 100 * (1 + factor) * precision * recall / (factor * precision + recall)


def corpus_chrf(hypotheses: Sequence[str], references: Sequence[str]) -> float:
    """chrF++ over a whole set, like sacrebleu's corpus_score"""
    totals = [0] * (3 * (CHAR_ORDER + WORD_ORDER))
    for hypothesis, reference in zip(hypotheses, references, strict=True):
        for i, value in enumerate(chrf_statistics(hypothesis, reference)):
            totals[i] += value
    return chrf_from_statistics(totals)


# --- data -----------------------------------------------------------------------


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{number}: not an object")
                rows.append(row)
    return rows


def load_sources(data: Path = DATA) -> Dict[str, Dict[str, Any]]:
    sources = {row["id"]: row for row in _read_jsonl(data / "sources.jsonl")}
    for row in sources.values():
        if not {"id", "domain", "text"} <= row.keys():
            raise ValueError(f"source {row.get('id')!r} needs id, domain and text")
    return sources


def load_languages(data: Path = DATA) -> Dict[str, Dict[str, Any]]:
    with (data / "languages.json").open(encoding="utf-8") as handle:
        return {row["code"]: row for row in json.load(handle)}


def load_references(
    language: str, sources: Dict[str, Dict[str, Any]], data: Path = DATA
) -> List[Dict[str, Any]]:
    """A language's references, checked against the sources; empty when there are none yet"""
    path = data / "references" / f"{language}.jsonl"
    if not path.exists():
        return []
    references = _read_jsonl(path)
    seen = set()
    for row in references:
        if row.get("id") not in sources:
            raise ValueError(f"{path}: unknown source id {row.get('id')!r}")
        if row["id"] in seen:
            raise ValueError(f"{path}: duplicate id {row['id']!r}")
        seen.add(row["id"])
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError(f"{path}: {row['id']} has no text")
        if not isinstance(row.get("reviewed"), bool):
            raise ValueError(f"{path}: {row['id']} needs reviewed: true or false")
    return references


# --- running --------------------------------------------------------------------


def _chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def translate_all(
    client: httpx.Client, texts: List[str], source: str, target: str
) -> Tuple[List[Optional[str]], int, float]:
    """Translate in batches; returns (translations or None per text, failed batches, seconds)"""
    results: List[Optional[str]] = []
    failures = 0
    started = time.monotonic()
    for batch in _chunks(texts, BATCH_SIZE):
        try:
            response = client.post(
                "/v1/translate/batch",
                json={"texts": batch, "from_language": source, "to_language": target},
            )
            translations = response.json().get("translations") if response.is_success else None
        except (httpx.HTTPError, ValueError):
            translations = None
        if not isinstance(translations, list) or len(translations) != len(batch):
            failures += 1
            results += [None] * len(batch)
            continue
        results += [
            item.get("translated_text") if isinstance(item, dict) else item for item in translations
        ]
    return results, failures, time.monotonic() - started


def evaluate_direction(
    client: httpx.Client,
    pairs: List[Tuple[str, str, str]],  # (id, input text, expected text)
    source: str,
    target: str,
    domains: Dict[str, str],
) -> Dict[str, Any]:
    """Translate one direction and score it overall and per domain"""
    outputs, failed_batches, seconds = translate_all(
        client, [text for _, text, _ in pairs], source, target
    )
    scored = [
        (item_id, output, expected)
        for (item_id, _, expected), output in zip(pairs, outputs, strict=True)
        if isinstance(output, str)
    ]
    by_domain: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for item_id, output, expected in scored:
        by_domain[domains[item_id]].append((output, expected))
    return {
        "sentences": len(pairs),
        "scored": len(scored),
        "failed_batches": failed_batches,
        "seconds": round(seconds, 2),
        "chrf++": round(corpus_chrf([o for _, o, _ in scored], [e for _, _, e in scored]), 2)
        if scored
        else None,
        "by_domain": {
            domain: round(corpus_chrf([o for o, _ in rows], [e for _, e in rows]), 2)
            for domain, rows in sorted(by_domain.items())
        },
        "outputs": [{"id": item_id, "output": output} for item_id, output, _ in scored],
    }


def evaluate(
    client: httpx.Client,
    languages: Sequence[str],
    directions: Sequence[str] = ("en-x", "x-en"),
    include_unreviewed: bool = False,
    data: Path = DATA,
) -> Dict[str, Any]:
    sources = load_sources(data)
    known = load_languages(data)
    domains = {item_id: row["domain"] for item_id, row in sources.items()}
    report: Dict[str, Any] = {"languages": {}, "skipped": {}}

    for language in languages:
        info = known.get(language)
        if info is None:
            report["skipped"][language] = "not in languages.json"
            continue
        if info.get("status") != "supported":
            report["skipped"][language] = "collecting references; not supported by the API yet"
            continue
        references = [
            row
            for row in load_references(language, sources, data)
            if include_unreviewed or row["reviewed"]
        ]
        if not references:
            report["skipped"][language] = "no reviewed references yet"
            continue
        result: Dict[str, Any] = {"name": info["name"], "references": len(references)}
        if "en-x" in directions:
            pairs = [(row["id"], sources[row["id"]]["text"], row["text"]) for row in references]
            result["en-x"] = evaluate_direction(client, pairs, "en", language, domains)
        if "x-en" in directions:
            pairs = [(row["id"], row["text"], sources[row["id"]]["text"]) for row in references]
            result["x-en"] = evaluate_direction(client, pairs, language, "en", domains)
        report["languages"][language] = result
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Score translations on the native-speaker set")
    parser.add_argument("--base-url", default=os.getenv("EVAL_API_URL", ""))
    parser.add_argument(
        "--languages",
        help="comma-separated codes (default: every language in languages.json)",
    )
    parser.add_argument("--directions", default="en-x,x-en")
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("--base-url (or EVAL_API_URL) is required")

    languages = (
        [code.strip() for code in args.languages.split(",") if code.strip()]
        if args.languages
        else list(load_languages())
    )
    directions = [d.strip() for d in args.directions.split(",") if d.strip()]
    api_key = os.getenv("EVAL_API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=args.timeout) as client:
        report = evaluate(client, languages, directions, args.include_unreviewed)

    if args.output:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    for code, result in report["languages"].items():
        scores = ", ".join(
            f"{direction} chrF++ {result[direction]['chrf++']}"
            for direction in directions
            if direction in result
        )
        print(f"{code} ({result['references']} references): {scores}")
    for code, reason in report["skipped"].items():
        print(f"{code}: skipped ({reason})", file=sys.stderr)
    return 0 if report["languages"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
