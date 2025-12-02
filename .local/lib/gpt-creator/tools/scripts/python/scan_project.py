#!/usr/bin/env python3
"""Minimal dependency scanner producing catalog + FTS index for gpt-creator."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable, List

# ---------- configuration ----------
TEXT_ALLOW_EXT = {
    ext.strip()
    for ext in """
.md .mmd .txt .rst .adoc .csv .tsv
.yaml .yml .toml .ini .cfg .conf .json
.sql .ics
.py .js .ts .tsx .jsx .vue .css .scss .html .xml
.c .h .cpp .hpp .cc .go .rb .php .java .cs .sh .ps1 .pl .rs
""".split()
    if ext.strip()
}

BINARY_DENY_EXT = {
    ext.strip()
    for ext in """
.png .jpg .jpeg .gif .webp .bmp .pdf .zip .gz .bz2 .xz .7z .tar
.mp3 .wav .flac .mp4 .mov .mkv .avi .obj .stl .bin .o .a .so .dll .dylib
.class .jar .wasm
""".split()
    if ext.strip()
}

MAX_FILE_BYTES = max(64_000, int(os.getenv("GC_SCAN_MAX_FILE_BYTES", "1048576")))
EXCERPT_MAX_BYTES = max(8_000, int(os.getenv("GC_SCAN_EXCERPT_MAX_BYTES", "65536")))
EXCERPT_MAX_LINES = max(20, int(os.getenv("GC_SCAN_EXCERPT_MAX_LINES", "200")))
FOLLOWLINKS = False

EXCLUDES_ENV = os.getenv("GC_CONTEXT_EXCLUDES", "")


def _expand_brace_pattern(pattern: str) -> List[str]:
    if "{" not in pattern or "}" not in pattern:
        return [pattern]
    prefix, remainder = pattern.split("{", 1)
    body, suffix = remainder.split("}", 1)
    options = [opt.strip() for opt in body.split(",") if opt.strip()]
    if not options:
        return [pattern.replace("{", "").replace("}", "")]
    return [f"{prefix}{choice}{suffix}" for choice in options]


def _expand_patterns(patterns: Iterable[str]) -> List[str]:
    expanded: List[str] = []
    for pattern in patterns:
        if not pattern:
            continue
        expanded.extend(_expand_brace_pattern(pattern))
    return expanded


EXCLUDES = _expand_patterns(
    [entry.strip() for entry in re.split(r"[:\n]+", EXCLUDES_ENV) if entry.strip()]
)

ALWAYS_EXCLUDE_SUBSTR = (
    "/.gpt-creator/",
    "/.git/",
    "/node_modules/",
    "/dist/",
    "/build/",
    "/work/runs/",
    "/prompts/",
    "/__pycache__",
    "/library/caches/",
)

ALWAYS_EXCLUDE_SUFFIX = (".meta.json", ".lock")

RUN_DIR = os.getenv("GC_RUN_DIR") or os.getenv("GC_STAGING_RUN_DIR") or ""
RUN_DIR_REAL = os.path.realpath(RUN_DIR) if RUN_DIR else None

# ---------- helpers ----------


def normpath(path: Path) -> str:
    return path.as_posix()


def should_skip_path(path: Path) -> bool:
    candidate = normpath(path).lower()
    if any(marker in candidate for marker in ALWAYS_EXCLUDE_SUBSTR):
        return True
    if candidate.endswith(ALWAYS_EXCLUDE_SUFFIX):
        return True
    for pattern in EXCLUDES:
        needle = pattern.strip("*").lower()
        if needle and needle in candidate:
            return True
    return False


def skip_heavy_or_binary(path: Path) -> bool:
    lower = normpath(path).lower()
    _, ext = os.path.splitext(lower)
    if ext in BINARY_DENY_EXT:
        return True
    if TEXT_ALLOW_EXT and ext not in TEXT_ALLOW_EXT:
        return True
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return True
    except OSError:
        return True
    return False


def safe_walk(root: Path) -> Iterable[tuple[str, list[str], list[str]]]:
    seen = set()
    for base, dirs, files in os.walk(root, topdown=True, followlinks=FOLLOWLINKS):
        try:
            base_real = os.path.realpath(base)
        except OSError:
            dirs[:] = []
            continue
        if base_real in seen:
            dirs[:] = []
            continue
        seen.add(base_real)
        if RUN_DIR_REAL and (
            base_real == RUN_DIR_REAL or base_real.startswith(RUN_DIR_REAL + os.sep)
        ):
            dirs[:] = []
            continue
        filtered_dirs = []
        for name in dirs:
            sub = Path(base) / name
            if os.path.islink(sub):
                continue
            if should_skip_path(sub):
                continue
            filtered_dirs.append(name)
        dirs[:] = filtered_dirs
        yield base, dirs, files


def sha256_bytes(payload: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(payload)
    return digest.hexdigest()


def read_excerpt(path: Path) -> str:
    output: List[str] = []
    used = 0
    try:
        with io.open(path, "r", encoding="utf-8", errors="ignore", newline="") as handle:
            for idx, line in enumerate(handle):
                if idx >= EXCERPT_MAX_LINES:
                    break
                encoded = line.encode("utf-8", "ignore")
                if used + len(encoded) > EXCERPT_MAX_BYTES:
                    encoded = encoded[: EXCERPT_MAX_BYTES - used]
                    output.append(encoded.decode("utf-8", "ignore"))
                    break
                output.append(line)
                used += len(encoded)
    except Exception:
        return ""
    return "".join(output)


H1 = re.compile(r"^\s*#\s+(.+)$")
H2 = re.compile(r"^\s*##\s+(.+)$")


def summarize(text: str, ext: str) -> dict[str, object]:
    lines = text.splitlines()
    title = ""
    if ext in {".md", ".mmd", ".rst", ".adoc"}:
        for candidate in lines[:20]:
            match = H1.match(candidate)
            if match:
                title = match.group(1).strip()
                break
    if not title and lines:
        title = lines[0].strip()[:120]
    headings: List[str] = []
    if ext in {".md", ".mmd"}:
        for candidate in lines[:200]:
            match = H2.match(candidate)
            if match:
                headings.append(match.group(1).strip())
            if len(headings) >= 10:
                break
    abstract_parts: List[str] = []
    for candidate in lines:
        stripped = candidate.strip()
        if stripped:
            abstract_parts.append(stripped)
        elif abstract_parts:
            break
        if sum(len(part) for part in abstract_parts) > 600:
            break
    return {
        "title": title,
        "headings": headings,
        "abstract": " ".join(abstract_parts)[:600],
    }


def kind_for(path: Path, ext: str) -> str:
    name = path.name.lower()
    if "openapi" in name or name.endswith(".openapi.yaml") or name.endswith(".openapi.yml"):
        return "openapi"
    if "postman" in name or "insomnia" in name:
        return "api-client"
    if ext == ".sql":
        if "dump" in name or "seed" in name:
            return "sql-dump"
        return "sql"
    if ext == ".mmd":
        return "diagram"
    if ext in {".md", ".rst", ".adoc"}:
        return "doc"
    return ext.lstrip(".") or "text"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scan-json")
    args = parser.parse_args()

    root = Path(args.project).resolve()
    outdir = Path(args.out).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    catalog_path = outdir / "catalog.jsonl"
    db_path = outdir / "index.sqlite"
    scan_json_path = Path(args.scan_json).resolve() if args.scan_json else None

    rows: List[dict[str, object]] = []
    seen_hashes = set()
    now = int(time.time())

    for base, _, files in safe_walk(root):
        base_path = Path(base)
        for name in files:
            candidate = base_path / name
            if should_skip_path(candidate):
                continue
            if skip_heavy_or_binary(candidate):
                continue
            try:
                stat = candidate.stat()
            except OSError:
                continue
            excerpt = read_excerpt(candidate)
            try:
                with io.open(candidate, "rb") as handle:
                    chunk = handle.read(min(stat.st_size, 128 * 1024))
                file_hash = sha256_bytes(chunk + str(stat.st_size).encode())
            except Exception:
                file_hash = ""
            if file_hash and file_hash in seen_hashes:
                continue
            seen_hashes.add(file_hash)

            ext = candidate.suffix.lower()
            meta = summarize(excerpt, ext)
            rel = candidate.relative_to(root) if str(candidate).startswith(str(root)) else candidate
            rows.append(
                {
                    "path": normpath(candidate),
                    "relpath": normpath(rel),
                    "ext": ext,
                    "size": int(stat.st_size),
                    "mtime": int(stat.st_mtime),
                    "sha256": file_hash,
                    "kind": kind_for(candidate, ext),
                    "title": meta["title"],
                    "headings": meta["headings"],
                    "abstract": meta["abstract"],
                    "preview": excerpt,
                    "scanned_at": now,
                }
            )

    tmp_catalog = catalog_path.with_suffix(".tmp")
    with io.open(tmp_catalog, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_catalog, catalog_path)

    if scan_json_path:
        artifacts = [
            {
                "type": row["kind"],
                "confidence": 0.9,
                "path": row["path"],
                "relpath": row["relpath"],
                "sha256": row["sha256"],
                "size": row["size"],
            }
            for row in rows
        ]
        payload = {
            "project_root": str(root),
            "generated_at": now,
            "artifacts": artifacts,
        }
        scan_json_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_scan = scan_json_path.with_suffix(".tmp")
        with io.open(tmp_scan, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_scan, scan_json_path)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            path TEXT,
            relpath TEXT,
            ext TEXT,
            size INTEGER,
            mtime INTEGER,
            sha256 TEXT,
            kind TEXT,
            title TEXT,
            abstract TEXT,
            preview TEXT
        );
        """
    )
    try:
        cur.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
                title, abstract, preview, content='documents', content_rowid='id'
            );"""
        )
        has_fts = True
    except sqlite3.OperationalError:
        has_fts = False

    cur.executemany(
        """
        INSERT INTO documents (path, relpath, ext, size, mtime, sha256, kind, title, abstract, preview)
        VALUES (:path, :relpath, :ext, :size, :mtime, :sha256, :kind, :title, :abstract, :preview)
        """,
        rows,
    )
    if has_fts:
        cur.execute(
            "INSERT INTO fts(rowid, title, abstract, preview) SELECT id, title, abstract, preview FROM documents;"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind);")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
