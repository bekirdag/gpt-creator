#!/usr/bin/env python3
"""Check whether required discovery manifest entries are missing."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable


DEFAULT_REQUIRED = ["pdr", "sds", "rfp", "jira", "ui_pages", "openapi", "sql"]


def iter_found_entries(lines: Iterable[str]) -> dict[str, str]:
    entries: dict[str, str] = {}
    in_found = False
    base_indent: int | None = None

    for raw_line in lines:
        if not raw_line:
            continue
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        if stripped == "found:" and indent == 0:
            in_found = True
            base_indent = None
            continue
        if not in_found:
            continue
        if base_indent is None:
            if indent <= 0:
                in_found = False
                continue
            base_indent = indent
        if indent < base_indent or ":" not in stripped:
            in_found = False
            continue
        key, value = stripped.split(":", 1)
        entries[key.strip()] = value.strip()
    return entries


def is_empty(value: str | None) -> bool:
    if value is None:
        return True
    text = value.strip()
    return text in {"", "null", "~"}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(0)

    file_path = Path(sys.argv[1])
    required = sys.argv[2:] or DEFAULT_REQUIRED

    try:
        raw = file_path.read_text(encoding="utf-8")
    except Exception:
        raise SystemExit(0)

    entries = iter_found_entries(raw.splitlines())

    for key in required:
        if is_empty(entries.get(key)):
            raise SystemExit(0)

    raise SystemExit(1)


if __name__ == "__main__":
    main()
