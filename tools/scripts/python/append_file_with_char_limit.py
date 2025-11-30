#!/usr/bin/env python3
"""Append file contents to a destination file with an optional char limit."""

from __future__ import annotations

import sys
from pathlib import Path


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def main() -> int:
    if len(sys.argv) < 4:
        return 1

    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    max_chars = int(sys.argv[3])

    text = read_text(src)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n... (truncated; see source for full details)\n"
    if text and not text.endswith("\n"):
        text += "\n"

    with dest.open("a", encoding="utf-8") as handle:
        handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
