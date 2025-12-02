#!/usr/bin/env python3
"""Extract the first JSON object or array from a text file."""

import json
import sys
from pathlib import Path


def extract_json(raw_path: Path, out_path: Path) -> None:
    """Find the first JSON snippet in raw Codex output and pretty-print it."""
    text = raw_path.read_text(encoding="utf-8")
    stack = []
    start = None

    for idx, ch in enumerate(text):
        if ch in "{[":
            if not stack:
                start = idx
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
                if not stack and start is not None:
                    snippet = text[start : idx + 1]
                    try:
                        data = json.loads(snippet)
                    except json.JSONDecodeError:
                        continue
                    out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                    return

    raise SystemExit("Failed to locate JSON payload in Codex output")


def main(argv) -> None:
    if len(argv) != 3:
        raise SystemExit("Usage: extract_json.py INPUT OUTPUT")

    raw_path = Path(argv[1])
    out_path = Path(argv[2])
    extract_json(raw_path, out_path)


if __name__ == "__main__":
    main(sys.argv)
