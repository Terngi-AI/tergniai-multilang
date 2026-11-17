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
import re
import sys
from typing import List, Match, Optional, Sequence

# --- patterns -----------------------------------------------------------------

# https://example.com/path, www.example.org/tz, ...
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
# amina.yusuf+work@gmail.com, chidi_okeke@yahoo.co.uk, ...
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# +234 803 123 4567, +2348031234567, +233 24 123 4567, ...
_PHONE_INTL = re.compile(r"(?<!\d)\+\d{1,3}(?:[\s.-]?\d){7,14}(?!\d)")
# Local numbers without a country code: 0803 123 4567, 024 123 4567, (0803) 123-4567
_PHONE_LOCAL = re.compile(r"(?<!\d)(?:\(\d{1,4}\)[\s.-]?)?\d{2,4}(?:[\s.-]\d{2,4}){1,4}(?!\d)")
# A date such as 2026-10-25: phone-shaped but not one
_DATE = re.compile(r"\d{4}[-/. ]\d{1,2}[-/. ]\d{1,2}")
# Consecutive digit strings of 11+ (Nigerian BVN is 11 digits)
_LONG_DIGITS = re.compile(r"(?<!\d)\d{11,}(?!\d)")


def _phone_repl(match: Match[str]) -> str:
    """Keep dates and short numbers; mask everything phone-shaped"""
    if _DATE.fullmatch(match.group(0)):
        return match.group(0)
    if len(re.sub(r"\D", "", match.group(0))) < 7:
        return match.group(0)
    return "[PHONE]"


def redact_names(text: str, names: Sequence[str]) -> str:
    """Mask a list of known person names (longest first, case-insensitive)"""
    for name in sorted(names, key=len, reverse=True):
        pattern = r"\b" + re.escape(name) + r"\b"
        text = re.sub(pattern, "[NAME]", text, flags=re.IGNORECASE)
    return text


def redact(text: str, names: Sequence[str] = ()) -> str:
    """Mask e-mails, URLs, phone numbers, long digit strings and known names"""
    text = _URL.sub("[URL]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE_INTL.sub(_phone_repl, text)
    text = _PHONE_LOCAL.sub(_phone_repl, text)
    text = _LONG_DIGITS.sub("[ID]", text)
    return redact_names(text, names)


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
