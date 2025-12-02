#!/usr/bin/env python3
"""Normalize Codex review output to plain Markdown."""

import sys
from pathlib import Path


def strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text.strip()

    lines = text.splitlines()
    if not lines:
        return ""

    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def main(argv) -> None:
    if len(argv) != 3:
        raise SystemExit("Usage: extract_review_markdown.py INPUT_PATH OUTPUT_PATH")

    raw_path = Path(argv[1])
    out_path = Path(argv[2])
    text = raw_path.read_text(encoding="utf-8").strip()

    normalized = strip_code_fence(text)
    out_path.write_text(ensure_trailing_newline(normalized), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
