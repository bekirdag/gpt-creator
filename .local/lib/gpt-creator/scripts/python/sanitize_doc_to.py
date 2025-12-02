#!/usr/bin/env python3
"""Normalize documentation content for pipeline context generation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

CODE_BLOCK_MAX_LINES = 120
CODE_BLOCK_MAX_CHARS = 4000


def flush_code_block(
    cleaned: list[str],
    code_lines: list[str],
    code_header: str,
) -> None:
    if not code_lines:
        return
    body = "\n".join(code_lines)
    if CODE_BLOCK_MAX_LINES > 0:
        body_lines = body.splitlines()
        if len(body_lines) > CODE_BLOCK_MAX_LINES:
            body_lines = body_lines[:CODE_BLOCK_MAX_LINES]
            body_lines.append("... (code block truncated)")
        body = "\n".join(body_lines)
    if CODE_BLOCK_MAX_CHARS > 0 and len(body) > CODE_BLOCK_MAX_CHARS:
        body = body[:CODE_BLOCK_MAX_CHARS].rstrip() + "\n... (code block truncated)"
    cleaned.append(code_header or "```")
    cleaned.append(body)
    cleaned.append(code_header or "```")


def sanitize_doc(source: Path, dest: Path) -> None:
    try:
        text = source.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        dest.write_text("", encoding="utf-8")
        return

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if text.startswith("---\n"):
        end_idx = text.find("\n---", 4)
        if 0 <= end_idx <= 5000:
            text = text[end_idx + 4 :]

    lines = text.split("\n")
    cleaned: list[str] = []
    code_lines: list[str] = []
    in_code_block = False
    code_fence = ""
    code_header = ""
    skipping_toc = False
    toc_seen = False

    for raw_line in lines:
        line = raw_line.replace("\t", "  ")
        stripped = line.strip()
        lower = stripped.lower()

        if in_code_block:
            if stripped.startswith(code_fence):
                flush_code_block(cleaned, code_lines, code_header)
                code_lines = []
                in_code_block = False
                code_fence = ""
                code_header = ""
            else:
                code_lines.append(raw_line)
            continue

        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        if stripped.startswith("<!--"):
            continue
        if stripped.endswith("-->"):
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_block = True
            code_fence = stripped[:3]
            code_header = stripped if len(stripped) > 3 else code_fence
            code_lines = []
            continue

        if skipping_toc:
            if not stripped or stripped.startswith("#"):
                skipping_toc = False
            elif re.match(r"^(\s*[-*+]\s|\s*\d+\.\s)", stripped) or "(#" in stripped:
                continue
            else:
                skipping_toc = False

        if re.match(r"^#{1,6}\s+(table of contents|contents)\b", lower):
            skipping_toc = True
            toc_seen = True
            continue
        if not toc_seen and stripped.startswith("- [") and "(#" in stripped:
            continue

        if not stripped:
            if cleaned and cleaned[-1] == "":
                continue
            cleaned.append("")
            continue

        if len(stripped) > 800:
            continue

        if re.fullmatch(r"[-=_*]{4,}", stripped):
            continue

        cleaned.append(stripped)

    if in_code_block and code_lines:
        flush_code_block(cleaned, code_lines, code_header)

    clean_text = "\n".join(cleaned).strip()
    clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)
    dest.write_text(clean_text + ("\n" if clean_text else ""), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    source = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    sanitize_doc(source, dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
