"""
PII redaction for evaluation and training data

Anything published in this repository (evaluation sets, feedback exports, datasets under
`data/`) must have personal data removed before it is committed. This script masks:

- e-mail addresses        -> [EMAIL]
- URLs                    -> [URL]
- phone numbers           -> [PHONE]   (E.164 and common local formats)
- long digit strings      -> [ID]      (national IDs, bank verification numbers)
- known person names      -> [NAME]    (pass the list with --names; plug in NER if needed)

The tool errs on the side of over-redaction: masking a date or an order number is
acceptable, missing a phone number is not.

Usage:
    python scripts/redact_pii.py transcript.txt            # redacted text on stdout
    python scripts/redact_pii.py --names names.txt -       # read stdin, mask known names
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The patterns live in services/pii.py so the API (feedback redaction, PII_MASKING) and
# this script can't drift apart (#141)
from services.pii import redact, redact_names  # noqa: E402

__all__ = ["main", "redact", "redact_names"]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mask personal data (e-mails, URLs, phone numbers, IDs, names)"
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="files to redact, written to stdout (use - or omit for stdin)",
    )
    parser.add_argument(
        "--names",
        help="file with one known person name per line, masked as [NAME]",
    )
    args = parser.parse_args(argv)

    names: List[str] = []
    if args.names:
        with open(args.names, encoding="utf-8") as handle:
            names = [line.strip() for line in handle if line.strip()]

    chunks: List[str] = []
    if not args.files:
        chunks.append(sys.stdin.read())
    for path in args.files:
        if path == "-":
            chunks.append(sys.stdin.read())
        else:
            with open(path, encoding="utf-8") as handle:
                chunks.append(handle.read())

    for chunk in chunks:
        sys.stdout.write(redact(chunk, names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
