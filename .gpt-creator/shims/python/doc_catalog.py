#!/usr/bin/env python3
"""Lightweight documentation catalog helper used by gpt-creator.

The original shim shipped with the upstream automation project is absent in this
repository, which caused all catalog lookups to stall and eventually time out.
This replacement keeps the command surface compatible (`list`, `search`, `show`)
while avoiding any external dependencies. It prefers the SQLite catalog when
available, and otherwise falls back to scanning the docs/ tree directly.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional


DEFAULT_DIRECTORIES = ("docs",)
ALLOWED_SUFFIXES = {
    ".md",
    ".sql",
    ".mmd",
    ".json",
    ".txt",
}


@dataclass
class Document:
    doc_id: str
    path: Optional[Path]
    rel_path: Optional[Path] = None
    title: Optional[str] = None
    snippet: Optional[str] = None


def _candidate_paths(doc: Document) -> Iterator[Path]:
    seen: set[str] = set()
    for raw in (doc.path, doc.rel_path):
        if raw is None:
            continue
        base = raw if isinstance(raw, Path) else Path(str(raw))
        options = [base]
        if not base.is_absolute():
            options.append(Path.cwd() / base)
        for candidate in options:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            yield candidate


def _resolve_existing_path(doc: Document) -> Optional[Path]:
    for candidate in _candidate_paths(doc):
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def _display_path(doc: Document) -> str:
    for candidate in (doc.rel_path, doc.path):
        if candidate is not None:
            return str(candidate)
    return doc.doc_id


def hash_id(text: str) -> str:
    """Create a stable DOC-xxxxx identifier from an arbitrary string."""
    import hashlib

    digest = hashlib.sha1(text.encode("utf-8")).hexdigest().upper()
    return f"DOC-{digest[:8]}"


def iter_files(base_dirs: Iterable[Path]) -> Iterator[Path]:
    for base in base_dirs:
        if not base.exists():
            continue
        if base.is_file():
            yield base
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            yield path


def load_from_fs(limit: Optional[int] = None) -> list[Document]:
    cwd = Path.cwd()
    bases = [cwd / rel for rel in DEFAULT_DIRECTORIES]
    docs: list[Document] = []
    for path in iter_files(bases):
        rel = path.relative_to(cwd)
        docs.append(Document(doc_id=hash_id(str(rel)), path=path, rel_path=rel))
        if limit and len(docs) >= limit:
            break
    return docs


def load_from_sqlite(db_path: Path, limit: Optional[int] = None) -> list[Document]:
    docs: list[Document] = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("SELECT *, rowid AS __rowid FROM documents ORDER BY __rowid DESC")
        for row in cursor:
            row_dict = dict(row)
            path_value = row_dict.get("path") or row_dict.get("relpath") or row_dict.get("rel_path")
            rel_value = row_dict.get("relpath") or row_dict.get("rel_path")
            snippet_value = (
                row_dict.get("snippet")
                or row_dict.get("preview")
                or row_dict.get("abstract")
            )
            doc_identifier = row_dict.get("doc_id") or row_dict.get("id")
            if not doc_identifier:
                continue
            docs.append(
                Document(
                    doc_id=str(doc_identifier),
                    path=Path(path_value) if path_value else None,
                    rel_path=Path(rel_value) if rel_value else None,
                    title=row_dict.get("title"),
                    snippet=snippet_value,
                )
            )
            if limit and len(docs) >= limit:
                break
    finally:
        conn.close()
    return docs


def safe_load_from_sqlite(
    db_path: Optional[Path], limit: Optional[int] = None
) -> Optional[list[Document]]:
    if not have_sqlite_catalog(db_path):
        return None
    try:
        return load_from_sqlite(db_path, limit)
    except sqlite3.Error:
        return None


def have_sqlite_catalog(db_path: Optional[Path]) -> bool:
    if not db_path:
        return False
    return db_path.exists()


def resolve_db_path(args: argparse.Namespace) -> Optional[Path]:
    db = getattr(args, "db", None)
    if db:
        return Path(db)
    env = Path(".gpt-creator/staging/plan/tasks/tasks.db")
    return env if env.exists() else None


def cmd_list(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args)
    limit = args.limit
    docs = safe_load_from_sqlite(db_path, limit)
    if docs is None:
        docs = load_from_fs(limit)
    for doc in docs:
        title_part = f" — {doc.title}" if doc.title else ""
        print(f"{doc.doc_id}\t{_display_path(doc)}{title_part}")
    return 0


def match_query(text: str, query: str) -> bool:
    return query.lower() in text.lower()


def search_documents(
    docs: Iterable[Document], query: str, limit: Optional[int]
) -> Iterator[Document]:
    for doc in docs:
        resolved_path = _resolve_existing_path(doc)
        text = ""
        try:
            if resolved_path:
                text = resolved_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = resolved_path.read_text(encoding="utf-8", errors="ignore")  # type: ignore[arg-type]
        except OSError:
            text = ""
        if not text:
            fallback_parts = []
            if doc.title:
                fallback_parts.append(str(doc.title))
            if doc.snippet:
                fallback_parts.append(str(doc.snippet))
            text = "\n".join(part for part in fallback_parts if part).strip()
        if not text or not match_query(text, query):
            continue
        lines = text.splitlines()
        if (not doc.title) and lines:
            doc.title = lines[0].strip()
        snippet = (doc.snippet or "").strip()
        for idx, line in enumerate(lines, 1):
            if match_query(line, query):
                prefix = f"L{idx}: " if resolved_path else ""
                snippet = f"{prefix}{line.strip()}"
                break
        doc.snippet = snippet
        yield doc
        if limit and limit <= 1:
            return
        if limit:
            limit -= 1


def cmd_search(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args)
    limit = args.limit
    query = args.query
    base_docs = safe_load_from_sqlite(db_path)
    if base_docs is None:
        base_docs = load_from_fs()
    matches = list(search_documents(base_docs, query, limit))
    for doc in matches:
        snippet = f" — {doc.snippet}" if doc.snippet else ""
        print(f"{doc.doc_id}\t{_display_path(doc)}{snippet}")
    return 0 if matches else 1


def cmd_show(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args)
    doc_id = args.doc_id
    start = args.start or 1
    end = args.end
    docs = safe_load_from_sqlite(db_path)
    if docs is None:
        docs = load_from_fs()
    target = None
    for doc in docs:
        candidates = {doc.doc_id}
        if doc.path:
            candidates.add(str(doc.path))
        if doc.rel_path:
            candidates.add(str(doc.rel_path))
        if doc_id in candidates:
            target = doc
            break
    if target is None:
        print(f"Document '{doc_id}' not found.", file=sys.stderr)
        return 2
    path = _resolve_existing_path(target)
    if not path:
        print(
            f"Document '{doc_id}' path '{_display_path(target)}' is unavailable locally. "
            "Run 'gpt-creator scan' to refresh the catalog.",
            file=sys.stderr,
        )
        return 3
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    end = end or len(lines)
    for idx in range(start, end + 1):
        if idx <= 0 or idx > len(lines):
            continue
        print(f"{idx:>5} {lines[idx - 1]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc_catalog.py",
        description="Minimal documentation catalog helper.",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="Optional path to the SQLite catalog (falls back to docs/ scan).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List available documentation entries.")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="Search documentation content.")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--query", required=True)
    p_search.set_defaults(func=cmd_search)

    p_show = sub.add_parser("show", help="Show a document by ID or path.")
    p_show.add_argument("--doc-id", required=True)
    p_show.add_argument("--start", type=int)
    p_show.add_argument("--end", type=int)
    p_show.set_defaults(func=cmd_show)

    return parser


def normalize_global_args(argv: list[str]) -> list[str]:
    """Ensure global options (like --db) appear before subcommands."""
    if not argv:
        return []
    cleaned: list[str] = []
    db_arg: Optional[str] = None
    db_value: Optional[str] = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--db":
            if i + 1 < len(argv):
                db_arg = "--db"
                db_value = argv[i + 1]
                i += 2
                continue
            # dangling --db without value; let argparse surface the error
            cleaned.append(token)
            i += 1
            continue
        if token.startswith("--db="):
            db_arg = "--db="
            db_value = token.split("=", 1)[1]
            i += 1
            continue
        cleaned.append(token)
        i += 1

    if db_arg is None:
        return cleaned
    if db_arg == "--db":
        return ["--db", db_value or ""] + cleaned
    return [f"--db={db_value or ''}"] + cleaned


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    argv = normalize_global_args(list(argv))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Mirror standard CLI tools: silently exit when downstream pipe closes.
        raise SystemExit(0)
