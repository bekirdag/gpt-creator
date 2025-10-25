#!/usr/bin/env python3
"""
Persistent documentation registry for gpt-creator.

Stores canonical metadata for project documents (PDR, SDS, OpenAPI specs,
SQL dumps, etc.) inside the project-scoped SQLite database so every workflow
shares a single source of truth. Also tracks change history entries whenever
documents are created or updated by the tooling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union


def _iso_ts_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> Optional[str]:
    try:
        handle = path.open("rb")
    except OSError:
        return None
    digest = hashlib.sha256()
    with handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _file_stats(path: Path) -> tuple[Optional[int], Optional[int]]:
    try:
        stat = path.stat()
    except OSError:
        return (None, None)
    size = int(stat.st_size)
    mtime_ns = getattr(stat, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(stat.st_mtime * 1_000_000_000)
    return (size, int(mtime_ns))


def _normalise_path(value: Optional[Union[str, Path]]) -> Optional[str]:
    if not value:
        return None
    try:
        return str(Path(value).resolve())
    except OSError:
        return str(value)


def _file_name_parts(path: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not path:
        return (None, None)
    name = Path(path).name
    ext = Path(path).suffix.lstrip(".").lower() or None
    return (name, ext)


def _ensure_iter(value: Optional[Union[Sequence[str], str]]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _compact_tags(tags: Optional[Sequence[str]]) -> Optional[str]:
    items = sorted({tag.strip().lower() for tag in _ensure_iter(tags) if tag})
    if not items:
        return None
    return json.dumps(items, ensure_ascii=False)


def _normalise_metadata(metadata: Optional[dict]) -> Optional[str]:
    if not metadata:
        return None
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _derive_doc_id(doc_type: str, source_path: Optional[str], staging_path: Optional[str]) -> str:
    basis = source_path or staging_path or doc_type or "document"
    digest = hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:16].upper()
    return f"DOC-{digest}"


@dataclass
class DocumentInput:
    doc_type: str
    source_path: Optional[str] = None
    staging_path: Optional[str] = None
    rel_path: Optional[str] = None
    title: Optional[str] = None
    size_bytes: Optional[int] = None
    mtime_ns: Optional[int] = None
    sha256: Optional[str] = None
    tags: Optional[Sequence[str]] = None
    metadata: Optional[dict] = None
    context: str = "scan"
    doc_id: Optional[str] = None


@dataclass
class SectionInput:
    section_id: str
    doc_id: str
    parent_section_id: Optional[str]
    order_index: int
    title: str
    anchor: Optional[str] = None
    byte_start: Optional[int] = None
    byte_end: Optional[int] = None
    token_start: Optional[int] = None
    token_end: Optional[int] = None
    summary: Optional[str] = None
    last_synced_at: Optional[str] = None
    source_version: Optional[str] = None


@dataclass
class SearchEntry:
    doc_id: str
    section_id: Optional[str]
    surface: str
    content: str


class DocRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documentation (
              doc_id TEXT PRIMARY KEY,
              doc_type TEXT NOT NULL,
              source_path TEXT,
              staging_path TEXT,
              rel_path TEXT,
              file_name TEXT,
              file_ext TEXT,
              size_bytes INTEGER,
              mtime_ns INTEGER,
              sha256 TEXT,
              title TEXT,
              tags_json TEXT,
              metadata_json TEXT,
              discovered_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              change_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_type ON documentation(doc_type)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_source ON documentation(source_path)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_staging ON documentation(staging_path)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documentation_changes (
              change_id INTEGER PRIMARY KEY AUTOINCREMENT,
              doc_id TEXT NOT NULL,
              change_type TEXT NOT NULL,
              sha256 TEXT,
              size_bytes INTEGER,
              mtime_ns INTEGER,
              description TEXT,
              context TEXT,
              recorded_at TEXT NOT NULL,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_changes_doc ON documentation_changes(doc_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documentation_summaries (
              doc_id TEXT PRIMARY KEY,
              summary_short TEXT,
              summary_long TEXT,
              key_points_json TEXT,
              keywords_json TEXT,
              embedding_id TEXT,
              last_generated_at TEXT,
              generator_source TEXT,
              source_version TEXT,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documentation_sections (
              section_id TEXT PRIMARY KEY,
              doc_id TEXT NOT NULL,
              parent_section_id TEXT,
              order_index INTEGER NOT NULL,
              title TEXT NOT NULL,
              anchor TEXT,
              byte_start INTEGER,
              byte_end INTEGER,
              token_start INTEGER,
              token_end INTEGER,
              summary TEXT,
              last_synced_at TEXT,
              source_version TEXT,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE,
              FOREIGN KEY(parent_section_id) REFERENCES documentation_sections(section_id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_sections_doc ON documentation_sections(doc_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_sections_parent ON documentation_sections(parent_section_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documentation_excerpts (
              excerpt_id TEXT PRIMARY KEY,
              doc_id TEXT NOT NULL,
              section_id TEXT,
              content TEXT NOT NULL,
              justification TEXT,
              token_length INTEGER,
              embedding_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              source_version TEXT,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE,
              FOREIGN KEY(section_id) REFERENCES documentation_sections(section_id) ON DELETE SET NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_excerpts_doc ON documentation_excerpts(doc_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_excerpts_section ON documentation_excerpts(section_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS documentation_index_state (
              doc_id TEXT NOT NULL,
              surface TEXT NOT NULL,
              indexed_at TEXT,
              status TEXT,
              usage_score REAL,
              metadata_json TEXT,
              PRIMARY KEY (doc_id, surface),
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_documentation_index_state_surface ON documentation_index_state(surface)"
        )
        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS documentation_search USING fts5(
              doc_id,
              section_id,
              surface,
              content,
              tokenize='unicode61'
            )
            """
        )

    def replace_sections_bulk(
        self,
        sections_map: dict[str, Sequence[SectionInput]],
    ) -> None:
        if not sections_map:
            return
        with self._connect() as conn:
            self.ensure_schema(conn)
            cur = conn.cursor()
            for doc_id, sections in sections_map.items():
                cur.execute(
                    "DELETE FROM documentation_sections WHERE doc_id = ?",
                    (doc_id,),
                )
                if not sections:
                    continue
                cur.executemany(
                    """
                    INSERT INTO documentation_sections (
                      section_id,
                      doc_id,
                      parent_section_id,
                      order_index,
                      title,
                      anchor,
                      byte_start,
                      byte_end,
                      token_start,
                      token_end,
                      summary,
                      last_synced_at,
                      source_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            section.section_id,
                            section.doc_id,
                            section.parent_section_id,
                            section.order_index,
                            section.title,
                            section.anchor,
                            section.byte_start,
                            section.byte_end,
                            section.token_start,
                            section.token_end,
                            section.summary,
                            section.last_synced_at,
                            section.source_version,
                        )
                        for section in sections
                    ],
                )
            conn.commit()

    def replace_search_entries(
        self,
        search_map: dict[str, Sequence[SearchEntry]],
    ) -> None:
        if not search_map:
            return
        with self._connect() as conn:
            self.ensure_schema(conn)
            cur = conn.cursor()
            doc_ids = list(search_map.keys())
            cur.executemany(
                "DELETE FROM documentation_search WHERE doc_id = ?",
                ((doc_id,) for doc_id in doc_ids),
            )
            inserts: List[tuple[str, Optional[str], str, str]] = []
            for entries in search_map.values():
                for entry in entries:
                    if not entry.content:
                        continue
                    inserts.append(
                        (
                            entry.doc_id,
                            entry.section_id,
                            entry.surface,
                            entry.content,
                        )
                    )
            if inserts:
                cur.executemany(
                    "INSERT INTO documentation_search(doc_id, section_id, surface, content) VALUES (?, ?, ?, ?)",
                    inserts,
                )
            conn.commit()

    def update_index_state(
        self,
        doc_id: str,
        surface: str,
        *,
        indexed_at: Optional[str] = None,
        status: str = "ready",
        usage_score: Optional[float] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        timestamp = indexed_at or _iso_ts_now()
        metadata_json = (
            json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if metadata
            else None
        )
        with self._connect() as conn:
            self.ensure_schema(conn)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO documentation_index_state (doc_id, surface, indexed_at, status, usage_score, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, surface) DO UPDATE SET
                  indexed_at = excluded.indexed_at,
                  status = excluded.status,
                  usage_score = COALESCE(excluded.usage_score, documentation_index_state.usage_score),
                  metadata_json = excluded.metadata_json
                """,
                (doc_id, surface, timestamp, status, usage_score, metadata_json),
            )
            conn.commit()

    def upsert_document(self, payload: DocumentInput) -> str:
        with self._connect() as conn:
            self.ensure_schema(conn)
            doc_id = self._upsert_document(conn, payload)
            conn.commit()
            return doc_id

    def bulk_upsert(self, payloads: Iterable[DocumentInput]) -> List[str]:
        with self._connect() as conn:
            self.ensure_schema(conn)
            cur = conn.cursor()
            doc_ids: List[str] = []
            for payload in payloads:
                doc_id = self._upsert_document(conn, payload, cur=cur)
                doc_ids.append(doc_id)
            conn.commit()
            return doc_ids

    def _fetch_existing(
        self,
        cur: sqlite3.Cursor,
        *,
        doc_id: Optional[str],
        source_path: Optional[str],
        staging_path: Optional[str],
        doc_type: str,
    ) -> Optional[sqlite3.Row]:
        if doc_id:
            cur.execute("SELECT * FROM documentation WHERE doc_id = ?", (doc_id,))
            row = cur.fetchone()
            if row:
                return row
        if source_path:
            cur.execute(
                "SELECT * FROM documentation WHERE source_path = ? LIMIT 1", (source_path,)
            )
            row = cur.fetchone()
            if row:
                return row
        if staging_path:
            cur.execute(
                "SELECT * FROM documentation WHERE staging_path = ? LIMIT 1", (staging_path,)
            )
            row = cur.fetchone()
            if row:
                return row
        cur.execute(
            "SELECT * FROM documentation WHERE doc_type = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
            (doc_type,),
        )
        return cur.fetchone()

    def _record_change(
        self,
        cur: sqlite3.Cursor,
        doc_id: str,
        change_type: str,
        *,
        sha256: Optional[str],
        size_bytes: Optional[int],
        mtime_ns: Optional[int],
        context: str,
        description: Optional[str] = None,
    ) -> None:
        recorded_at = _iso_ts_now()
        cur.execute(
            """
            INSERT INTO documentation_changes (doc_id, change_type, sha256, size_bytes, mtime_ns, description, context, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, change_type, sha256, size_bytes, mtime_ns, description, context, recorded_at),
        )
        cur.execute(
            "UPDATE documentation SET change_count = change_count + 1, updated_at = ? WHERE doc_id = ?",
            (recorded_at, doc_id),
        )

    def _upsert_document(
        self,
        conn: sqlite3.Connection,
        payload: DocumentInput,
        *,
        cur: Optional[sqlite3.Cursor] = None,
    ) -> str:
        cursor = cur or conn.cursor()
        src_path = _normalise_path(payload.source_path)
        staged_path = _normalise_path(payload.staging_path)
        doc_id = payload.doc_id or _derive_doc_id(payload.doc_type, src_path, staged_path)
        existing = self._fetch_existing(
            cursor,
            doc_id=doc_id,
            source_path=src_path,
            staging_path=staged_path,
            doc_type=payload.doc_type,
        )
        now = _iso_ts_now()
        tags_json = _compact_tags(payload.tags)
        metadata_json = _normalise_metadata(payload.metadata)
        path_for_name = src_path or staged_path
        file_name, file_ext = _file_name_parts(path_for_name)
        size_bytes = payload.size_bytes
        mtime_ns = payload.mtime_ns
        sha256 = payload.sha256

        if size_bytes is None or mtime_ns is None or sha256 is None:
            reference_path = Path(src_path or staged_path) if (src_path or staged_path) else None
            if reference_path and reference_path.exists():
                computed_size, computed_mtime = _file_stats(reference_path)
                if size_bytes is None:
                    size_bytes = computed_size
                if mtime_ns is None:
                    mtime_ns = computed_mtime
                if sha256 is None:
                    sha256 = _sha256_file(reference_path)

        if existing is None:
            cursor.execute(
                """
                INSERT INTO documentation (
                  doc_id, doc_type, source_path, staging_path, rel_path, file_name, file_ext,
                  size_bytes, mtime_ns, sha256, title, tags_json, metadata_json,
                  discovered_at, updated_at, status, change_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0)
                """,
                (
                    doc_id,
                    payload.doc_type,
                    src_path,
                    staged_path,
                    payload.rel_path,
                    file_name,
                    file_ext,
                    size_bytes,
                    mtime_ns,
                    sha256,
                    payload.title,
                    tags_json,
                    metadata_json,
                    now,
                    now,
                ),
            )
            self._record_change(
                cursor,
                doc_id,
                "created",
                sha256=sha256,
                size_bytes=size_bytes,
                mtime_ns=mtime_ns,
                context=payload.context,
            )
            return doc_id

        doc_id = str(existing["doc_id"])
        fields_to_update: dict[str, object] = {}
        change_type: Optional[str] = None

        def _update_field(column: str, new_value: Optional[object]) -> None:
            nonlocal fields_to_update
            current = existing[column]
            if new_value is None:
                return
            if current == new_value:
                return
            fields_to_update[column] = new_value

        if src_path:
            _update_field("source_path", src_path)
        if staged_path:
            _update_field("staging_path", staged_path)
        if payload.rel_path:
            _update_field("rel_path", payload.rel_path)
        if file_name:
            _update_field("file_name", file_name)
        if file_ext:
            _update_field("file_ext", file_ext)
        if payload.title:
            _update_field("title", payload.title)
        if tags_json:
            _update_field("tags_json", tags_json)
        if metadata_json:
            _update_field("metadata_json", metadata_json)
        if size_bytes is not None:
            _update_field("size_bytes", size_bytes)
        if mtime_ns is not None:
            _update_field("mtime_ns", mtime_ns)
        if sha256 is not None:
            if existing["sha256"] != sha256:
                change_type = "modified"
            _update_field("sha256", sha256)

        if not fields_to_update:
            return doc_id

        if change_type is None:
            change_type = "metadata"

        fields_to_update["updated_at"] = now
        set_clause = ", ".join(f"{column} = ?" for column in fields_to_update)
        params = list(fields_to_update.values())
        params.append(doc_id)
        cursor.execute(f"UPDATE documentation SET {set_clause} WHERE doc_id = ?", params)

        self._record_change(
            cursor,
            doc_id,
            change_type,
            sha256=sha256 or existing["sha256"],
            size_bytes=size_bytes or existing["size_bytes"],
            mtime_ns=mtime_ns or existing["mtime_ns"],
            context=payload.context,
        )
        return doc_id

    def fetch_all(self, *, include_inactive: bool = False) -> List[dict]:
        with self._connect() as conn:
            self.ensure_schema(conn)
            cursor = conn.cursor()
            if include_inactive:
                cursor.execute("SELECT * FROM documentation ORDER BY doc_type, file_name")
            else:
                cursor.execute(
                    "SELECT * FROM documentation WHERE status = 'active' ORDER BY doc_type, file_name"
                )
            rows = []
            for row in cursor.fetchall():
                entry = dict(row)
                tags_json = entry.get("tags_json")
                entry["tags"] = json.loads(tags_json) if tags_json else []
                metadata_json = entry.get("metadata_json")
                entry["metadata"] = json.loads(metadata_json) if metadata_json else {}
                rows.append(entry)
            return rows


SCAN_CATEGORY_MAP = {
    "pdr": "pdr",
    "sds": "sds",
    "rfp": "rfp",
    "openapi": "openapi",
    "swagger": "openapi",
    "sql": "sql",
    "jira": "jira",
    "ui_pages_doc": "ui",
    "mermaid_backoffice": "diagram",
    "mermaid_website": "diagram",
    "mermaid_unknown": "diagram",
    "page_sample_website": "sample",
    "page_sample_backoffice": "sample",
    "page_sample_unknown": "sample",
    "page_samples_root": "sample",
    "page_samples_website_dir": "sample",
    "page_samples_backoffice_dir": "sample",
    "raid_log": "raid-log",
}


def _runtime_db_path(runtime_dir: Path) -> Path:
    return runtime_dir / "staging" / "plan" / "tasks" / "tasks.db"


def _parse_scan_tsv(tsv_path: Path, project_root: Path) -> List[DocumentInput]:
    candidates: dict[tuple[str, str], dict] = {}
    try:
        raw_lines = tsv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for line in raw_lines:
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("category"):
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        category, score_str, path_str = parts
        doc_type = SCAN_CATEGORY_MAP.get(category.strip().lower())
        if not doc_type:
            continue
        try:
            score = int(score_str.strip())
        except ValueError:
            score = 0
        path_obj = Path(path_str.strip()).expanduser()
        if not path_obj.exists() or not path_obj.is_file():
            continue
        resolved = str(path_obj.resolve())
        key = (doc_type, resolved)
        entry = candidates.get(key)
        if entry is None or score > entry["score"]:
            rel_path = None
            try:
                rel_path = str(path_obj.resolve().relative_to(project_root))
            except Exception:
                rel_path = str(path_obj)
            entry = {
                "doc_type": doc_type,
                "resolved": resolved,
                "rel_path": rel_path,
                "score": score,
                "tags": set([doc_type, category.strip().lower()]),
            }
            candidates[key] = entry
        else:
            entry["tags"].add(category.strip().lower())

    payloads: List[DocumentInput] = []
    for entry in candidates.values():
        path_obj = Path(entry["resolved"])
        size, mtime_ns = _file_stats(path_obj)
        sha256 = _sha256_file(path_obj)
        payloads.append(
            DocumentInput(
                doc_type=entry["doc_type"],
                source_path=str(path_obj),
                rel_path=entry["rel_path"],
                size_bytes=size,
                mtime_ns=mtime_ns,
                sha256=sha256,
                tags=list(entry["tags"]),
                context="scan",
            )
        )
    return payloads


def _handle_sync_scan(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    runtime_dir = Path(args.runtime_dir).resolve()
    scan_tsv = Path(args.scan_tsv).resolve()
    db_path = _runtime_db_path(runtime_dir)
    registry = DocRegistry(db_path)
    payloads = _parse_scan_tsv(scan_tsv, project_root)
    if not payloads:
        return 0
    registry.bulk_upsert(payloads)
    return 0


def _handle_register(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir).resolve()
    db_path = _runtime_db_path(runtime_dir)
    registry = DocRegistry(db_path)
    metadata = json.loads(args.metadata) if args.metadata else None
    tags = json.loads(args.tags) if args.tags else None
    hash_path: Optional[Path] = None
    if args.source_path:
        hash_path = Path(args.source_path)
    elif args.staging_path:
        hash_path = Path(args.staging_path)
    payload = DocumentInput(
        doc_type=args.doc_type,
        source_path=args.source_path,
        staging_path=args.staging_path,
        rel_path=args.rel_path,
        title=args.title,
        size_bytes=int(args.size_bytes) if args.size_bytes is not None else None,
        mtime_ns=int(args.mtime_ns) if args.mtime_ns is not None else None,
        sha256=args.sha256,
        tags=tags,
        metadata=metadata,
        context=args.context or "manual",
        doc_id=args.doc_id,
    )
    if args.compute_hash and not payload.sha256 and hash_path and hash_path.exists():
        payload.sha256 = _sha256_file(hash_path)
    registry.upsert_document(payload)
    return 0


def _handle_export(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir).resolve()
    db_path = _runtime_db_path(runtime_dir)
    registry = DocRegistry(db_path)
    rows = registry.fetch_all(include_inactive=args.include_inactive)
    sys.stdout.write(json.dumps(rows, indent=2, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage gpt-creator documentation registry.")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_scan = sub.add_parser("sync-scan", help="Ingest scan discovery results into the registry.")
    sync_scan.add_argument("--project-root", required=True, help="Project root used during scan.")
    sync_scan.add_argument("--runtime-dir", required=True, help="Runtime directory (e.g., .gpt-creator).")
    sync_scan.add_argument("--scan-tsv", required=True, help="Scan TSV output file.")
    sync_scan.set_defaults(func=_handle_sync_scan)

    register = sub.add_parser("register", help="Register or update a single document entry.")
    register.add_argument("--runtime-dir", required=True)
    register.add_argument("--doc-type", required=True)
    register.add_argument("--source-path")
    register.add_argument("--staging-path")
    register.add_argument("--rel-path")
    register.add_argument("--title")
    register.add_argument("--size-bytes")
    register.add_argument("--mtime-ns")
    register.add_argument("--sha256")
    register.add_argument("--tags", help="JSON array of tags.")
    register.add_argument("--metadata", help="JSON object of metadata.")
    register.add_argument("--context", default="manual")
    register.add_argument("--doc-id")
    register.add_argument("--compute-hash", action="store_true", help="Compute file hash when missing.")
    register.set_defaults(func=_handle_register)

    export = sub.add_parser("export", help="Emit registry contents as JSON.")
    export.add_argument("--runtime-dir", required=True)
    export.add_argument("--include-inactive", action="store_true")
    export.set_defaults(func=_handle_export)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
