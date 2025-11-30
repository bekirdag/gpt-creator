#!/usr/bin/env python3
"""Trim prompt files for lean retries with tighter context slices."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        raise SystemExit(0)

    max_files = int(os.environ.get("CODEX_CONTEXT_MAX_FILES", "8") or 8)
    slice_lines = int(os.environ.get("CODEX_CONTEXT_SLICE_LINES", "80") or 80)
    digest_lines = int(os.environ.get("CODEX_SHARED_DIGEST_LINES", "150") or 150)
    max_chars = int(os.environ.get("CODEX_LEAN_CHAR_LIMIT", "20000") or 20000)

    text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    sections = text.split("\n### ")
    head = sections[0]
    entries = []
    for raw in sections[1:]:
        if "\n" in raw:
            title, body = raw.split("\n", 1)
        else:
            title, body = raw, ""
        entries.append((title.strip(), body))

    trimmed_sections = []
    notes = []
    for idx, (title, body) in enumerate(entries):
        if idx >= max_files:
            notes.append(f"shared context trimmed: dropped section '{title}' (beyond max files {max_files}).")
            continue
        lines = body.splitlines()
        limit = digest_lines if "shared context digest" in title.lower() else slice_lines
        if len(lines) > limit:
            notes.append(f"shared context trimmed: '{title}' reduced to {limit} lines (was {len(lines)}).")
        trimmed_body = "\n".join(lines[:limit]).rstrip()
        trimmed_sections.append(f"### {title}\n{trimmed_body}\n")

    result = head.rstrip()
    if trimmed_sections:
        result = result + "\n" + "\n".join(trimmed_sections)

    if len(result) > max_chars:
        notes.append(f"prompt truncated to {max_chars} characters for lean retry (was {len(result)}).")
        result = result[:max_chars].rstrip()

    if notes:
        result = result.rstrip() + "\n\n[lean-mode prompt reduction applied]\n"

    if result != original:
        path.write_text(result, encoding="utf-8")
        print("[prompt-lean] prompt reduced for lean retry:")
        for note in notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()

