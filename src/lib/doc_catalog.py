#!/usr/bin/env python3
"""
Build and persist a documentation catalog for gpt-creator.

The catalog consolidates staged documentation files (PDR, SDS, RFP, OpenAPI,
SQL schemas, etc.) into a JSON index plus human-friendly Markdown summaries.
It mirrors the structure consumed by the work-on-tasks loop so downstream runs
can reuse identifiers, headings, and metadata without rebuilding the catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


ALLOWED_EXTS = {
    ".md",
    ".markdown",
    ".mdx",
    ".txt",
    ".adoc",
    ".rst",
    ".mmd",
    ".sql",
    ".json",
    ".yaml",
    ".yml",
}

# Files without extensions that we still want (e.g., README)
ALLOWED_BARE_NAMES = {
    "readme",
    "rfp",
    "pdr",
    "sds",
}

KEYWORD_TAGS = {
    "pdr": "pdr",
    "product-requirements": "pdr",
    "product_requirements": "pdr",
    "sds": "sds",
    "system-design": "sds",
    "system_design": "sds",
    "rfp": "rfp",
    "openapi": "openapi",
    "swagger": "openapi",
    "sql": "sql",
    "schema": "sql",
    "diagram": "diagram",
    "mermaid": "diagram",
    "ui": "ui",
    "pages": "ui",
    "component": "ui",
    "seed": "seed",
    "migration": "sql",
}

# Directories to skip entirely when scanning the staging tree.
SKIP_DIR_PARTS = {
    "work",
    "runs",
    "tasks",
    "out",
    "tmp",
    "tmpfs",
}

MAX_HEADINGS = 80
MAX_PREVIEW_LINES = 12
MAX_SCAN_BYTES = 1_000_000  # 1 MB per file (sufficient for headings)
TOKEN_PATTERN = re.compile(r"\S+")


@dataclass
class DocHeading:
    title: str
    line: int
    level: int = 1


@dataclass
class DocEntry:
    doc_id: str
    path: Path
    rel_path: str
    size: int
    mtime_ns: int
    sha256: str
    title: str
    tags: List[str] = field(default_factory=list)
    headings: List[DocHeading] = field(default_factory=list)

    def to_catalog_payload(self) -> dict:
        return {
            "path": str(self.path),
            "rel_path": self.rel_path,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256,
            "title": self.title,
            "tags": self.tags,
            "headings": [
                {"title": h.title, "line": h.line, "level": h.level}
                for h in self.headings
            ],
        }


def human_size(value: int) -> str:
    thresholds = [
        (1_000_000_000, "GB"),
        (1_000_000, "MB"),
        (1_000, "KB"),
    ]
    for limit, label in thresholds:
        if value >= limit:
            return f"{value / float(limit):.1f} {label}"
    return f"{value} B"


def iso_ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def candidate_directories(staging_dir: Path) -> List[Path]:
    roots = [
        staging_dir / "docs",
        staging_dir / "plan" / "pdr",
        staging_dir / "plan" / "sds",
        staging_dir / "plan" / "docs",
        staging_dir / "plan" / "create-pdr",
        staging_dir / "plan" / "create-sds",
        staging_dir / "openapi",
        staging_dir / "sql",
        staging_dir / "normalized",
    ]
    seen: List[Path] = []
    for root in roots:
        if root.exists():
            seen.append(root)
    if staging_dir.exists():
        seen.append(staging_dir)
    return seen


def should_skip(path: Path, staging_dir: Path) -> bool:
    try:
        rel = path.relative_to(staging_dir)
    except ValueError:
        rel = path
    parts = {part.lower() for part in rel.parts}
    if parts & SKIP_DIR_PARTS:
        return True
    if path.name.startswith("."):
        return True
    return False


def allowed_file(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() in ALLOWED_EXTS:
        return True
    stem = path.stem.lower()
    if stem in ALLOWED_BARE_NAMES:
        return True
    return False


def detect_tags(rel_path: str) -> List[str]:
    lowered = rel_path.lower()
    tags = []
    for keyword, tag in KEYWORD_TAGS.items():
        if keyword in lowered and tag not in tags:
            tags.append(tag)
    return tags


def stable_doc_id(path: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    digest = hashlib.sha256(str(resolved).encode("utf-8", "replace")).hexdigest()
    return "DOC-" + digest[:8].upper()


def stable_section_id(doc_id: str, title: str, line: int) -> str:
    basis = f"{doc_id}:{line}:{title}".encode("utf-8", "replace")
    digest = hashlib.sha256(basis).hexdigest()[:12].upper()
    return f"SEC-{digest}"


def slugify_anchor(title: str, existing: Dict[str, int]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = "section"
    count = existing.get(slug, 0)
    existing[slug] = count + 1
    if count:
        slug = f"{slug}-{count}"
    return slug


def build_token_index(text: str) -> List[int]:
    return [match.start() for match in TOKEN_PATTERN.finditer(text)]


def token_index_at_offset(starts: List[int], offset: int) -> int:
    if not starts:
        return 0
    if offset <= 0:
        return 0
    return bisect_left(starts, offset, lo=0, hi=len(starts))


def build_line_offsets(text: str) -> List[int]:
    offsets: List[int] = []
    pos = 0
    for line in text.splitlines(True):
        offsets.append(pos)
        pos += len(line)
    return offsets


def read_limited_text(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(MAX_SCAN_BYTES)
    except OSError:
        return ""
    try:
        return chunk.decode("utf-8", "replace")
    except UnicodeDecodeError:
        return chunk.decode("latin-1", "replace")


def read_full_text_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def decode_text(data: bytes) -> str:
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace")


def extract_markdown_headings(text: str) -> List[DocHeading]:
    headings: List[DocHeading] = []
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        if len(headings) >= MAX_HEADINGS:
            break
        line = raw_line.strip()
        if not line:
            continue
        hash_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if hash_match:
            level = len(hash_match.group(1))
            title = hash_match.group(2).strip()
            if title:
                headings.append(DocHeading(title=title, line=idx, level=level))
                continue
        enumerated_match = re.match(
            r"^((?:\d+\.)+\d*|\d+|[A-Z][.)]|[IVXLCM]+\.)\s+(.*)$", line
        )
        if enumerated_match:
            title = enumerated_match.group(2).strip()
            if title:
                headings.append(DocHeading(title=title, line=idx, level=2))
                continue
    return headings


def extract_yaml_headings(text: str) -> List[DocHeading]:
    headings: List[DocHeading] = []
    pattern = re.compile(r"^([A-Za-z0-9_\- ]+):")
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        if len(headings) >= MAX_HEADINGS:
            break
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  "):
            continue
        match = pattern.match(line)
        if match:
            title = match.group(1).strip()
            if title:
                headings.append(DocHeading(title=title, line=idx, level=1))
    return headings


def extract_json_headings(text: str) -> List[DocHeading]:
    headings: List[DocHeading] = []
    try:
        payload = json.loads(text)
    except Exception:
        return headings
    if isinstance(payload, dict):
        for key in list(payload.keys())[:MAX_HEADINGS]:
            headings.append(DocHeading(title=str(key), line=1, level=1))
    return headings


def extract_sql_headings(text: str) -> List[DocHeading]:
    headings: List[DocHeading] = []
    pattern = re.compile(r"^\s*(CREATE|ALTER)\s+(TABLE|VIEW)\s+`?([A-Za-z0-9_]+)`?", re.I)
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        if len(headings) >= MAX_HEADINGS:
            break
        match = pattern.match(raw_line)
        if match:
            verb, obj_type, name = match.group(1, 2, 3)
            title = f"{verb.upper()} {obj_type.upper()} {name}"
            headings.append(DocHeading(title=title, line=idx, level=1))
    return headings


def extract_headings(path: Path, text: str) -> List[DocHeading]:
    lower_suffix = path.suffix.lower()
    if lower_suffix in {".md", ".markdown", ".mdx", ".txt", ".adoc", ".rst"}:
        return extract_markdown_headings(text)
    if lower_suffix in {".yaml", ".yml"}:
        headings = extract_yaml_headings(text)
        if headings:
            return headings
    if lower_suffix == ".json":
        headings = extract_json_headings(text)
        if headings:
            return headings
    if lower_suffix == ".sql":
        return extract_sql_headings(text)
    # Fallback to markdown-style parsing for other text files.
    return extract_markdown_headings(text)


def title_from_headings(path: Path, headings: Sequence[DocHeading]) -> str:
    if headings:
        for heading in headings:
            if heading.level <= 2 and heading.title:
                return heading.title
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() or path.name


def relative_path(path: Path, roots: Iterable[Path]) -> str:
    for root in roots:
        try:
            rel = path.relative_to(root)
            return str(rel)
        except ValueError:
            continue
    return str(path)


def build_sections(
    entry: DocEntry,
    section_cls,
    *,
    now_ts: str,
) -> List:
    data = read_full_text_bytes(entry.path)
    text = decode_text(data)
    char_offsets = build_line_offsets(text)
    byte_offsets: List[int] = []
    byte_pos = 0
    for line_bytes in data.splitlines(True):
        byte_offsets.append(byte_pos)
        byte_pos += len(line_bytes)
    total_chars = len(text)
    total_bytes = len(data)
    line_char_map = {idx + 1: offset for idx, offset in enumerate(char_offsets)}
    line_byte_map = {idx + 1: offset for idx, offset in enumerate(byte_offsets)}
    line_char_map[len(char_offsets) + 1] = total_chars
    line_byte_map[len(byte_offsets) + 1] = total_bytes
    sections: List = []
    token_starts = build_token_index(text)
    root_id = stable_section_id(entry.doc_id, "root", 0)
    sections.append(
        section_cls(
            section_id=root_id,
            doc_id=entry.doc_id,
            parent_section_id=None,
            order_index=0,
            title=entry.title or entry.rel_path,
            anchor="root",
            byte_start=0 if total_bytes else None,
            byte_end=total_bytes if total_bytes else None,
            token_start=0,
            token_end=len(token_starts),
            summary=None,
            last_synced_at=now_ts,
            source_version=entry.sha256,
        )
    )
    if not entry.headings:
        return sections
    anchor_counts: Dict[str, int] = {"root": 1}
    child_counts: Dict[str, int] = defaultdict(int)
    stack: List[tuple[int, str]] = [(0, root_id)]
    sorted_headings = sorted(entry.headings, key=lambda item: (item.line, item.level))
    for idx, heading in enumerate(sorted_headings):
        level = max(1, heading.level)
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_id = stack[-1][1] if stack else root_id
        child_index = child_counts[parent_id]
        child_counts[parent_id] = child_index + 1
        section_id = stable_section_id(entry.doc_id, heading.title, heading.line)
        anchor = slugify_anchor(heading.title, anchor_counts)
        next_line = (
            sorted_headings[idx + 1].line
            if idx + 1 < len(sorted_headings)
            else len(char_offsets) + 1
        )
        char_start = line_char_map.get(heading.line, 0)
        char_end = line_char_map.get(next_line, total_chars)
        byte_start = line_byte_map.get(heading.line)
        byte_end = line_byte_map.get(next_line, total_bytes)
        token_start = token_index_at_offset(token_starts, char_start)
        token_end = token_index_at_offset(token_starts, char_end)
        sections.append(
            section_cls(
                section_id=section_id,
                doc_id=entry.doc_id,
                parent_section_id=parent_id,
                order_index=child_index,
                title=heading.title,
                anchor=anchor,
                byte_start=byte_start,
                byte_end=byte_end,
                token_start=token_start,
                token_end=token_end,
                summary=None,
                last_synced_at=now_ts,
                source_version=entry.sha256,
            )
        )
        stack.append((level, section_id))
    return sections


def collect_documents(project_root: Path, staging_dir: Path) -> List[DocEntry]:
    roots = candidate_directories(staging_dir)
    docs: List[DocEntry] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if should_skip(path, staging_dir):
                continue
            if not allowed_file(path):
                continue
            text = read_limited_text(path)
            headings = extract_headings(path, text)
            rel = relative_path(
                path,
                [
                    project_root,
                    staging_dir,
                ],
            )
            try:
                stat = path.stat()
                size = int(stat.st_size)
                mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
            except OSError:
                size = 0
                mtime_ns = 0
            sha_hash = file_sha256(path)
            entry = DocEntry(
                doc_id=stable_doc_id(path),
                path=path,
                rel_path=rel,
                size=size,
                mtime_ns=mtime_ns,
                sha256=sha_hash,
                title=title_from_headings(path, headings),
                tags=detect_tags(rel),
                headings=list(headings)[:MAX_HEADINGS],
            )
            docs.append(entry)
    # Deduplicate by doc_id keeping newest mtime.
    latest: dict[str, DocEntry] = {}
    for entry in docs:
        existing = latest.get(entry.doc_id)
        if existing is None or entry.mtime_ns >= existing.mtime_ns:
            latest[entry.doc_id] = entry
    return sorted(latest.values(), key=lambda item: item.rel_path.lower())


def load_existing_catalog(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "documents": {}}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {"version": 1, "documents": {}}
    except Exception:
        return {"version": 1, "documents": {}}
    if not isinstance(data, dict):
        return {"version": 1, "documents": {}}
    if "documents" not in data or not isinstance(data["documents"], dict):
        data["documents"] = {}
    return data


def persist_catalog(
    catalog_path: Path,
    documents: Sequence[DocEntry],
) -> dict:
    catalog = load_existing_catalog(catalog_path)
    existing_docs = catalog.setdefault("documents", {})
    # Prune entries that no longer exist on disk.
    live_ids = {entry.doc_id for entry in documents}
    to_remove = [doc_id for doc_id in existing_docs if doc_id not in live_ids]
    for doc_id in to_remove:
        existing_docs.pop(doc_id, None)
    for entry in documents:
        payload = entry.to_catalog_payload()
        existing_docs[entry.doc_id] = payload
    catalog["version"] = 1
    catalog["generated_at"] = iso_ts_now()
    catalog["doc_count"] = len(existing_docs)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return catalog


def write_library_markdown(
    out_path: Path,
    documents: Sequence[DocEntry],
) -> None:
    lines: List[str] = []
    lines.append("# Documentation Library")
    lines.append("")
    lines.append(f"Generated {iso_ts_now()} (UTC).")
    lines.append("")
    if not documents:
        lines.append("_No staged documentation files discovered._")
    else:
        lines.append("| Doc ID | Relative Path | Title | Size | Tags |")
        lines.append("| --- | --- | --- | ---:| --- |")
        for entry in documents:
            tags = ", ".join(entry.tags) if entry.tags else "—"
            size_label = human_size(entry.size)
            title = entry.title or entry.rel_path
            lines.append(
                f"| {entry.doc_id} | `{entry.rel_path}` | {title} | {size_label} | {tags} |"
            )
    for entry in documents:
        lines.append("")
        lines.append(f"## {entry.doc_id} — {entry.rel_path}")
        lines.append("")
        if entry.title:
            lines.append(f"- **Title:** {entry.title}")
        lines.append(f"- **Size:** {human_size(entry.size)}")
        lines.append(f"- **Updated:** {datetime.fromtimestamp(entry.mtime_ns / 1_000_000_000, timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}")
        tags = ", ".join(entry.tags) if entry.tags else "—"
        lines.append(f"- **Tags:** {tags}")
        if entry.headings:
            lines.append("")
            lines.append("### Headings")
            for heading in entry.headings[:MAX_PREVIEW_LINES]:
                indent = "  " * max(0, heading.level - 1)
                label = f"{heading.title} (line {heading.line})"
                lines.append(f"{indent}- {label}")
            if len(entry.headings) > MAX_PREVIEW_LINES:
                remaining = len(entry.headings) - MAX_PREVIEW_LINES
                lines.append(f"  - … {remaining} additional heading(s) omitted")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_index_markdown(
    out_path: Path,
    documents: Sequence[DocEntry],
) -> None:
    lines: List[str] = []
    lines.append("# Documentation Index")
    lines.append("")
    lines.append("Each entry summarises the first ten headings detected per document.")
    lines.append("")
    if not documents:
        lines.append("_No documentation detected._")
    else:
        for entry in documents:
            lines.append(f"- **{entry.doc_id}** `{entry.rel_path}`")
            preview = entry.headings[:10]
            if not preview:
                lines.append("  - (no headings detected)")
                continue
            for heading in preview:
                indent = "    " * max(0, heading.level - 1)
                lines.append(f"{indent}- {heading.title} (line {heading.line})")
            if len(entry.headings) > len(preview):
                remaining = len(entry.headings) - len(preview)
                lines.append(f"    - … {remaining} more heading(s)")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


DOC_TYPE_ORDER = [
    "pdr",
    "sds",
    "rfp",
    "openapi",
    "sql",
    "jira",
    "ui",
    "diagram",
    "sample",
    "seed",
]


def infer_doc_type(entry: DocEntry) -> str:
    for candidate in DOC_TYPE_ORDER:
        if candidate in entry.tags:
            return candidate
    return entry.tags[0] if entry.tags else "document"


def sync_registry(staging_dir: Path, documents: Sequence[DocEntry]) -> None:
    try:
        from .doc_registry import DocRegistry, DocumentInput, SectionInput
    except Exception:
        try:
            from doc_registry import DocRegistry, DocumentInput, SectionInput  # type: ignore
        except Exception:
            return
    runtime_dir = staging_dir.parent
    db_path = runtime_dir / "staging" / "plan" / "tasks" / "tasks.db"
    try:
        registry = DocRegistry(db_path)
    except Exception:
        return
    payloads: List[DocumentInput] = []
    sections_map: Dict[str, List[SectionInput]] = {}
    for entry in documents:
        doc_type = infer_doc_type(entry)
        headings_payload = [
            {"title": h.title, "line": h.line, "level": h.level} for h in entry.headings
        ]
        metadata = {
            "catalog_doc_id": entry.doc_id,
            "headings": headings_payload,
        }
        payloads.append(
            DocumentInput(
                doc_type=doc_type,
                staging_path=str(entry.path),
                rel_path=entry.rel_path,
                title=entry.title,
                size_bytes=entry.size,
                mtime_ns=entry.mtime_ns,
                sha256=entry.sha256,
                tags=entry.tags,
                metadata=metadata,
                context="doc-catalog",
                doc_id=entry.doc_id,
            )
        )
        now_ts = iso_ts_now()
        sections = build_sections(entry, SectionInput, now_ts=now_ts)
        sections_map[entry.doc_id] = sections
    if payloads:
        registry.bulk_upsert(payloads)
    if sections_map:
        registry.replace_sections_bulk(sections_map)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build documentation catalog for staged files.")
    parser.add_argument("--project-root", required=True, help="Absolute path to the project root.")
    parser.add_argument("--staging-dir", required=True, help="Path to the .gpt-creator staging directory.")
    parser.add_argument("--out-json", required=True, help="Path to write doc-catalog.json.")
    parser.add_argument("--out-library", required=True, help="Path to write the Markdown library summary.")
    parser.add_argument("--out-index", required=True, help="Path to write the Markdown index/TOC.")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).expanduser()
    staging_dir = Path(args.staging_dir).expanduser()
    documents = collect_documents(project_root, staging_dir)
    catalog_path = Path(args.out_json).expanduser()
    persist_catalog(catalog_path, documents)
    write_library_markdown(Path(args.out_library).expanduser(), documents)
    write_index_markdown(Path(args.out_index).expanduser(), documents)
    sync_registry(staging_dir, documents)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
