#!/usr/bin/env python3
"""
Export opt-in translation feedback as evaluation-set JSON Lines

Examples:
    python scripts/export_feedback.py
    python scripts/export_feedback.py --output eval/feedback.jsonl
    python scripts/export_feedback.py --all
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.feedback import FeedbackError, load_records  # noqa: E402


def evaluation_record(
    record: Dict[str, Any], include_all: bool = False
) -> Optional[Dict[str, Any]]:
    """Convert one stored feedback record, or return None when it has no usable reference"""
    # Never export records without explicit consent, even if a file was edited by hand.
    if record.get("consent") is not True:
        return None

    correction = record.get("correction")
    rating = record.get("rating")
    reference = correction or (record.get("translated_text") if rating == "good" else None)
    if not reference and not include_all:
        return None

    source = record.get("source_text")
    from_language = record.get("from_language")
    to_language = record.get("to_language")
    if not all(isinstance(value, str) and value for value in (source, from_language, to_language)):
        return None

    exported: Dict[str, Any] = {
        "source": source,
        "reference": reference,
        "from_language": from_language,
        "to_language": to_language,
        "provider": record.get("provider", "unknown"),
    }
    if include_all:
        exported["rating"] = rating
        exported["correction"] = correction
    return exported


def build_records(
    records: Iterable[Dict[str, Any]], include_all: bool = False
) -> List[Dict[str, Any]]:
    """Convert records in order, removing exact duplicates from the default export"""
    exported: List[Dict[str, Any]] = []
    seen = set()
    for record in records:
        item = evaluation_record(record, include_all=include_all)
        if item is None:
            continue
        if not include_all:
            key = (item["source"], item["reference"], item["from_language"], item["to_language"])
            if key in seen:
                continue
            seen.add(key)
        exported.append(item)
    return exported


def write_jsonl(records: Iterable[Dict[str, Any]], output: Path) -> int:
    """Write JSON Lines (UTF-8, one object per line) and return the number of records"""
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "eval" / "feedback.jsonl",
        help="destination JSONL file (default: eval/feedback.jsonl)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="also export bad ratings without a correction (as negative examples)",
    )
    args = parser.parse_args()

    try:
        records = asyncio.run(load_records())
    except FeedbackError as e:
        print(f"Could not read feedback storage: {e}", file=sys.stderr)
        return 1

    exported = build_records(records, include_all=args.all)
    count = write_jsonl(exported, args.output)
    print(f"Exported {count} feedback record(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
