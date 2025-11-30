#!/usr/bin/env python3
"""Detect GA4 lockout payload references for telemetry checks."""

import re
import sys
from pathlib import Path


def extract_snippet(path: Path) -> str | None:
    content = path.read_text(encoding="utf-8")
    match = re.search(r"adminLoginLockoutGa\s*\(.*?\)", content, re.S)
    if not match:
        return None
    snippet = match.group(0)
    return snippet[:200]


def main() -> int:
    if len(sys.argv) < 2:
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        return 1

    snippet = extract_snippet(path)
    if snippet is None:
        return 1

    print(snippet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
