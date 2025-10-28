#!/usr/bin/env python3
"""Fetch a single environment variable value from a file."""

from __future__ import annotations

import sys
from pathlib import Path


def extract_value(line: str, key: str) -> str | None:
    if line.startswith(f"{key}="):
        return line[len(key) + 1 :].strip()
    if line.startswith(f"export {key}="):
        return line[len(key) + 8 :].strip()
    return None


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(0)
    file_path = Path(sys.argv[1])
    key = sys.argv[2]
    if not file_path.exists():
        raise SystemExit(0)
    for raw in file_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        value = extract_value(raw, key)
        if value is None:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        print(value)
        break


if __name__ == "__main__":
    main()
