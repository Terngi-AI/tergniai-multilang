#!/usr/bin/env python3
"""
Export the OpenAPI schema for the public API reference

The website (terngiai.com/developers) publishes the schema generated here rather than a
hand-edited copy, so the published reference cannot drift from the code.

Examples:
    python scripts/export_openapi.py
    python scripts/export_openapi.py --servers-url https://api.terngiai.com --output openapi.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The app refuses to import with auth disabled without an explicit opt-in (and, once
# keyed hashes land, without HASH_SECRET). The export serves no requests, so
# placeholders are enough.
os.environ.setdefault("ALLOW_UNAUTHENTICATED", "true")
os.environ.setdefault("HASH_SECRET", "openapi-export-placeholder")

from main import app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--servers-url",
        default="https://api.terngiai.com",
        help="base URL the exported schema points at (default: https://api.terngiai.com)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "openapi.json",
        help="destination JSON file (default: openapi.json)",
    )
    args = parser.parse_args()

    schema: Dict[str, Any] = app.openapi()
    schema["servers"] = [{"url": args.servers_url}]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(schema, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
