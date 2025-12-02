#!/usr/bin/env python3
"""Split Codex review output into schema and seed SQL files."""

from __future__ import annotations

import sys
from pathlib import Path


def _normalize(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return ""
    if not content.endswith("\n"):
        stripped += "\n"
    return stripped


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: split_codex_review_dump.py <raw> <schema> <seed>")

    raw_path = Path(sys.argv[1])
    schema_path = Path(sys.argv[2])
    seed_path = Path(sys.argv[3])

    raw = raw_path.read_text(encoding="utf-8").strip()
    if not raw:
        schema_sql = ""
        seed_sql = ""
    else:
        parts = raw.split("\n\n", 1)
        if len(parts) == 2:
            schema_sql, seed_sql = parts
        else:
            schema_sql, seed_sql = raw, ""

    schema_path.write_text(_normalize(schema_sql), encoding="utf-8")
    seed_path.write_text(_normalize(seed_sql), encoding="utf-8")


if __name__ == "__main__":
    main()
