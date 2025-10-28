#!/usr/bin/env python3
"""Render a context snippet from normalized manifest and optional catalog inputs."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def parse_int(env: str, default: int) -> int:
    try:
        return int(os.environ.get(env, default))
    except Exception:
        return default


def limited_section(path: Path, max_lines: int, max_chars: int, notice: str) -> List[str]:
    if not path or not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return []
    lines = raw.splitlines()
    truncated = False
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    joined = "\n".join(lines)
    if max_chars > 0 and len(joined) > max_chars:
        joined = joined[:max_chars].rstrip()
        truncated = True
    section_lines = joined.splitlines()
    if truncated and notice:
        section_lines.append(notice)
    return section_lines


def normalise_key(text: str) -> str:
    return text.replace("\\", "/").strip().lower()


def build_excerpt(text: str, char_limit: int, paragraph_limit: int) -> Tuple[str, bool]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks: List[str] = []
    current: List[str] = []
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if stripped:
            current.append(stripped)
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    if not blocks:
        fallback = " ".join(text.split())
        if char_limit > 0 and len(fallback) > char_limit:
            return fallback[:char_limit].rstrip() + "…", True
        return fallback, False
    excerpt_parts: List[str] = []
    total_chars = 0
    truncated = False
    for block in blocks:
        if not block:
            continue
        candidate = block
        block_len = len(candidate)
        if char_limit > 0 and total_chars + block_len > char_limit:
            allowance = char_limit - total_chars
            if allowance > 0:
                candidate = candidate[:allowance].rstrip()
                if candidate:
                    candidate += "…"
                    excerpt_parts.append(candidate)
            truncated = True
            break
        excerpt_parts.append(candidate)
        total_chars += block_len
        if paragraph_limit > 0 and len(excerpt_parts) >= paragraph_limit:
            truncated = True
            break
    if not excerpt_parts:
        return "", truncated
    return "\n".join(excerpt_parts), truncated


def load_manifest(path: Path) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    if not path.exists():
        return entries
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        if "\t" in raw_line:
            original, cleaned = raw_line.split("\t", 1)
        else:
            original = cleaned = raw_line
        entries.append((original.strip(), cleaned.strip()))
    return entries


def load_catalog(path: Path) -> Dict[str, Dict[str, str]]:
    catalog: Dict[str, Dict[str, str]] = {}
    if not path or not path.exists():
        return catalog
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return catalog
    if not isinstance(payload, dict):
        return catalog
    for key, value in payload.items():
        if isinstance(value, dict):
            catalog[normalise_key(key)] = {k: str(v) for k, v in value.items()}
    return catalog


def load_library(path: Path, max_lines: int, max_chars: int) -> List[str]:
    notice = "... (truncated; consult doc-library.md for more)"
    return limited_section(path, max_lines, max_chars, notice)


def load_index(path: Path, max_lines: int, max_chars: int) -> List[str]:
    notice = "... (truncated; consult doc-index.md for more)"
    return limited_section(path, max_lines, max_chars, notice)


def render_context_snippet(
    manifest_path: Path,
    output_path: Path,
    catalog_path: Path | None,
    library_path: Path | None,
    index_path: Path | None,
) -> None:
    manifest_entries = load_manifest(manifest_path)

    DOC_LIBRARY_LINES = parse_int("CJT_DOC_LIBRARY_SECTION_LINES", 48)
    DOC_LIBRARY_CHAR_LIMIT = parse_int("CJT_DOC_LIBRARY_SECTION_CHAR_LIMIT", 2200)
    DOC_INDEX_LINES = parse_int("CJT_DOC_INDEX_SECTION_LINES", 72)
    DOC_INDEX_CHAR_LIMIT = parse_int("CJT_DOC_INDEX_SECTION_CHAR_LIMIT", 2600)
    DOC_HEADINGS_LIMIT = parse_int("CJT_DOC_HEADINGS_LIMIT", 8)
    DOC_EXCERPT_CHAR_LIMIT = parse_int("CJT_DOC_EXCERPT_CHAR_LIMIT", 900)
    DOC_EXCERPT_PARAGRAPH_LIMIT = parse_int("CJT_DOC_EXCERPT_PARAGRAPH_LIMIT", 5)

    legacy_lines = os.environ.get("CJT_CONTEXT_SNIPPET_LINES")
    if legacy_lines and "CJT_DOC_EXCERPT_PARAGRAPH_LIMIT" not in os.environ:
        try:
            DOC_EXCERPT_PARAGRAPH_LIMIT = int(legacy_lines)
        except Exception:
            pass
    legacy_chars = os.environ.get("CJT_CONTEXT_SNIPPET_CHAR_LIMIT")
    if legacy_chars and "CJT_DOC_EXCERPT_CHAR_LIMIT" not in os.environ:
        try:
            DOC_EXCERPT_CHAR_LIMIT = int(legacy_chars)
        except Exception:
            pass

    catalog = load_catalog(catalog_path) if catalog_path else {}
    library_section = load_library(library_path, DOC_LIBRARY_LINES, DOC_LIBRARY_CHAR_LIMIT) if library_path else []
    index_section = load_index(index_path, DOC_INDEX_LINES, DOC_INDEX_CHAR_LIMIT) if index_path else []

    lines_out: List[str] = []
    if library_section:
        lines_out.append("## Documentation Library")
        lines_out.extend(library_section)
        lines_out.append("")
    if index_section:
        lines_out.append("## Documentation Index")
        lines_out.extend(index_section)
        lines_out.append("")

    used_headings = 0
    used_keys: set[str] = set()

    for original, cleaned in manifest_entries:
        key_norm = normalise_key(cleaned or original)
        if key_norm in used_keys:
            continue
        used_keys.add(key_norm)

        meta = catalog.get(key_norm, {})
        doc_type = meta.get("doc_type", "")
        title = meta.get("title") or cleaned or original
        headings = meta.get("headings_json")
        excerpt = meta.get("excerpt")
        content_path = meta.get("content_path")

        lines_out.append(f"## {title}")
        if doc_type:
            lines_out.append(f"_Type_: {doc_type}")

        heading_lines: List[str] = []
        if headings:
            try:
                data = json.loads(headings)
                if isinstance(data, list):
                    for entry in data:
                        heading = (entry or "").strip()
                        if not heading:
                            continue
                        heading_lines.append(f"- {heading}")
                        if DOC_HEADINGS_LIMIT > 0 and len(heading_lines) >= DOC_HEADINGS_LIMIT:
                            heading_lines.append("... (additional headings truncated)")
                            break
            except Exception:
                heading_lines = []

        if heading_lines:
            lines_out.append("")
            lines_out.append("### Headings")
            lines_out.extend(heading_lines)

        excerpt_text: str | None = None
        truncated = False
        if excerpt:
            excerpt_text = excerpt
        elif content_path:
            try:
                excerpt_text = Path(content_path).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                excerpt_text = None

        if excerpt_text:
            if content_path:
                excerpt_title = "Excerpt"
            else:
                excerpt_title = "Summary"
            rendered_excerpt, truncated_excerpt = build_excerpt(
                excerpt_text, DOC_EXCERPT_CHAR_LIMIT, DOC_EXCERPT_PARAGRAPH_LIMIT
            )
            truncated = truncated_excerpt
            lines_out.append("")
            lines_out.append(f"### {excerpt_title}")
            lines_out.append(rendered_excerpt)
            if truncated and content_path:
                lines_out.append("... (excerpt truncated; review source document for full details)")

        if content_path:
            lines_out.append("")
            lines_out.append(f"_Source_: {content_path}")

        lines_out.append("")
        used_headings += 1

    output_path.write_text("\n".join(lines_out).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        return 1

    manifest_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    catalog_path = Path(sys.argv[3]).expanduser() if len(sys.argv) > 3 and sys.argv[3] else None
    library_path = Path(sys.argv[4]).expanduser() if len(sys.argv) > 4 and sys.argv[4] else None
    index_path = Path(sys.argv[5]).expanduser() if len(sys.argv) > 5 and sys.argv[5] else None

    render_context_snippet(manifest_path, output_path, catalog_path, library_path, index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
