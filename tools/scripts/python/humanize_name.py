#!/usr/bin/env python3
"""Generate a human-friendly project name from a path or slug."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def humanize(raw: str) -> str:
    if raw:
        raw = Path(raw).name
    raw = re.sub(r"[_\-]+", " ", raw).strip()
    if not raw:
        return "Project"

    words: list[str] = []
    for token in raw.split():
        if len(token) <= 3:
            words.append(token.upper())
        elif token.isupper():
            words.append(token)
        else:
            words.append(token.capitalize())
    return " ".join(words)


def main() -> int:
    value = sys.argv[1] if len(sys.argv) > 1 else ""
    print(humanize(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
