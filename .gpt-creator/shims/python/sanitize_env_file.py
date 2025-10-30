#!/usr/bin/env python3
"""Clean .env files by removing invalid or unsafe entries."""

from __future__ import annotations

import re
import sys
from pathlib import Path


PATTERN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
WHITESPACE_RE = re.compile(r"\s")
NUMERIC_KEYS = {"DB_HOST_PORT", "DB_PORT", "MYSQL_HOST_PORT"}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        raise SystemExit(0)

    lines = path.read_text(encoding="utf-8").splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            cleaned.append(line)
            continue
        match = PATTERN.match(line)
        if not match:
            continue
        key, value = match.groups()
        value = ANSI_RE.sub("", value).strip()
        if "➜" in value or "remapping" in value or value.startswith("Port "):
            continue
        if key.endswith("_HOST_PORT") or key in NUMERIC_KEYS:
            if not value.isdigit():
                continue
        if WHITESPACE_RE.search(value):
            if not (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                continue
        cleaned.append(f"{key}={value}")

    path.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")


if __name__ == "__main__":
    main()

