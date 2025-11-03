#!/usr/bin/env python3
"""Lightweight documentation catalog helper used by gpt-creator.

The original catalog tooling depends on a prebuilt SQLite index that may not be
present in local worktrees, which caused helper invocations to stall for 10–30
seconds before timing out. This replacement keeps the same command surface
(`list`, `search`, `show`) but gracefully falls back to scanning the repository
when the database is unavailable.
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


@dataclass
class Document:
    doc_id: str
    path: Path
    title: Optional[str] = None
    snippet: Optional[str] = None


def hash_id(text: str) -> str:
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
        docs.append(Document(doc_id=hash_id(str(rel)), path=rel))
        if limit and len(docs) >= limit:
            break
    return docs


def load_from_sqlite(
    db_path: Path, limit: Optional[int] = None
) -> list[Document]:
    docs: list[Document] = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT id, path, title, snippet FROM documents ORDER BY updated_at DESC"
        )
        for row in cursor:
            docs.append(
                Document(
                    doc_id=row["id"],
                    path=Path(row["path"]),
                    title=row["title"],
                    snippet=row["snippet"],
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
    return bool(db_path and db_path.exists())


def resolve_db_path(args: argparse.Namespace) -> Optional[Path]:
    db = getattr(args, "db", None)
    if db:
        candidate = Path(db)
        return candidate if candidate.exists() else None
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
        print(f"{doc.doc_id}\t{doc.path}{title_part}")
    return 0


def match_query(text: str, query: str) -> bool:
    return query.lower() in text.lower()


def search_documents(
    docs: Iterable[Document], query: str, limit: Optional[int]
) -> Iterator[Document]:
    for doc in docs:
        path = Path(doc.path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        if not match_query(text, query):
            continue
        doc.title = doc.title or (text.splitlines()[0].strip() if text else "")
        snippet = ""
        for idx, line in enumerate(text.splitlines(), 1):
            if match_query(line, query):
                snippet = f"L{idx}: {line.strip()}"
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
        print(f"{doc.doc_id}\t{doc.path}{snippet}")
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
        if doc.doc_id == doc_id or str(doc.path) == doc_id:
            target = doc
            break
    if target is None:
        print(f"Document '{doc_id}' not found.", file=sys.stderr)
        return 2
    path = Path(target.path)
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
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--db",
        metavar="PATH",
        help="Optional path to the SQLite catalog (falls back to docs/ scan).",
    )

    parser = argparse.ArgumentParser(
        prog="doc_catalog.py",
        description="Minimal documentation catalog helper.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser(
        "list", parents=[common], help="List available documentation entries."
    )
    p_list.add_argument("--limit", type=int, default=10)
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser(
        "search", parents=[common], help="Search documentation content."
    )
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--query", required=True)
    p_search.set_defaults(func=cmd_search)

    p_show = sub.add_parser(
        "show", parents=[common], help="Show a document by ID or path."
    )
    p_show.add_argument("--doc-id", required=True)
    p_show.add_argument("--start", type=int)
    p_show.add_argument("--end", type=int)
    p_show.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
