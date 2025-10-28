#!/usr/bin/env python3
"""Generate a summary of epic context with configurable limits."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def parse_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except Exception:
        return default
    return value


def build_summary(source: Path, dest: Path) -> None:
    section_limit = parse_int("CJT_EPIC_CONTEXT_SECTION_LIMIT", 6)
    snippet_char_limit = parse_int("CJT_EPIC_CONTEXT_SECTION_CHAR_LIMIT", 900)
    total_char_limit = parse_int("CJT_EPIC_CONTEXT_TOTAL_CHAR_LIMIT", 4500)

    if not source.exists():
        dest.write_text("", encoding="utf-8")
        return

    raw = source.read_text(encoding="utf-8", errors="ignore")
    lines = raw.splitlines()

    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_title is not None:
                body = "\n".join(current_lines).strip()
                if body:
                    sections.append((current_title, body))
            current_title = line[3:].strip() or "Section"
            current_lines = []
            continue
        if line.startswith("# "):
            continue
        if current_title is None:
            continue
        current_lines.append(line)

    if current_title is not None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_title, body))

    filtered_sections: list[tuple[str, str]] = []
    for title, body in sections:
        lowered = title.strip().lower()
        if lowered.startswith("documentation library") or lowered.startswith("documentation table of contents"):
            continue
        filtered_sections.append((title, body))
    sections = filtered_sections

    if not sections:
        trimmed = raw.strip()
        if total_char_limit > 0 and len(trimmed) > total_char_limit:
            trimmed = trimmed[:total_char_limit].rstrip() + "\n... (truncated; consult consolidated context for full details)"
        dest.write_text(trimmed + ("\n" if trimmed else ""), encoding="utf-8")
        return

    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "system",
        "user",
        "story",
        "should",
        "will",
        "must",
        "allow",
        "support",
        "able",
        "data",
        "api",
        "admin",
        "project",
        "documentation",
        "context",
        "section",
    }
    token_re = re.compile(r"[a-z0-9][a-z0-9\-_/]{2,}")

    scored: list[tuple[int, int, int, str, str]] = []
    for index, (title, body) in enumerate(sections):
        tokens = {token.strip("-_/") for token in token_re.findall(body.lower()) if len(token) > 3}
        keywords = {token for token in tokens if token and token not in stopwords}
        unique_score = len(keywords)
        length_score = min(len(body), 2000)
        scored.append((unique_score, length_score, index, title, body))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))

    selected: list[tuple[str, str]] = []
    total_chars = 0
    remaining_sections = len(scored) if section_limit <= 0 else min(section_limit, len(scored))

    for unique_score, length_score, index, title, body in scored:
        if remaining_sections == 0:
            break
        snippet = body
        if snippet_char_limit > 0 and len(snippet) > snippet_char_limit:
            snippet = snippet[:snippet_char_limit].rstrip() + "\n... (truncated; consult consolidated context for full details)"
        snippet_len = len(snippet)
        if total_char_limit > 0 and total_chars + snippet_len > total_char_limit:
            allowance = total_char_limit - total_chars
            if allowance <= 0:
                break
            snippet = snippet[:allowance].rstrip()
            if snippet:
                snippet += "\n... (truncated; consult consolidated context for full details)"
                snippet_len = len(snippet)
            else:
                break
        selected.append((title, snippet))
        total_chars += snippet_len
        remaining_sections -= 1

    if not selected and scored:
        fallback = scored[0][4]
        if total_char_limit > 0 and len(fallback) > total_char_limit:
            fallback = fallback[:total_char_limit].rstrip() + "\n... (truncated; consult consolidated context for full details)"
        dest.write_text(fallback + ("\n" if fallback else ""), encoding="utf-8")
        return

    lines_out: list[str] = []
    for title, snippet in selected:
        lines_out.append(f"### {title}")
        lines_out.append(snippet)
        lines_out.append("")

    dest.write_text("\n".join(lines_out), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    source = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    build_summary(source, dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
