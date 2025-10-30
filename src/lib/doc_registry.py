#!/usr/bin/env python3
"""
Documentation registry implementation used by the scanning/catalog pipeline.

The registry is responsible for:
  * maintaining the SQLite schema (documentation rows, sections, search index);
  * ingesting discovery manifests produced by `gpt-creator scan`;
  * serving structured rows back to catalog builders; and
  * accepting bulk upserts from `doc_catalog.py` so headings/metadata stay in sync.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stable_doc_id(path: Path) -> str:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    digest = hashlib.sha256(str(resolved).encode("utf-8", "replace")).hexdigest()
    return "DOC-" + digest[:8].upper()


def _sha256(path: Path) -> str:
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


def _safe_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _normalize_tags(tags: Sequence[str]) -> List[str]:
    seen: Dict[str, None] = {}
    for tag in tags:
        if not tag:
            continue
        slug = str(tag).strip().lower()
        if not slug:
            continue
        seen.setdefault(slug, None)
    return sorted(seen)


@dataclass(frozen=True)
class DocumentInput:
    doc_id: str
    doc_type: str
    source_path: Optional[str] = None
    staging_path: Optional[str] = None
    rel_path: Optional[str] = None
    title: Optional[str] = None
    size_bytes: Optional[int] = None
    mtime_ns: Optional[int] = None
    sha256: Optional[str] = None
    tags: Sequence[str] = ()
    metadata: Optional[Dict[str, object]] = None
    context: Optional[str] = None
    status: str = "active"
    file_name: Optional[str] = None
    file_ext: Optional[str] = None


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class SummaryInput:
    doc_id: str
    summary_short: str
    summary_long: str
    key_points: Sequence[str] = ()
    keywords: Sequence[str] = ()
    embedding_id: Optional[str] = None
    last_generated_at: Optional[str] = None
    generator_source: str = "heuristic"
    source_version: Optional[str] = None


@dataclass(frozen=True)
class ExcerptInput:
    excerpt_id: str
    doc_id: str
    section_id: Optional[str]
    content: str
    justification: Optional[str] = None
    token_length: Optional[int] = None
    embedding_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    source_version: Optional[str] = None


@dataclass(frozen=True)
class SearchEntry:
    doc_id: str
    section_id: Optional[str]
    surface: str
    content: str
    updated_at: Optional[str] = None


class DocRegistry:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._apply_pragmas(conn)
            self._ensure_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON;")

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documentation (
              doc_id         TEXT PRIMARY KEY,
              doc_type       TEXT NOT NULL,
              source_path    TEXT,
              staging_path   TEXT,
              rel_path       TEXT,
              file_name      TEXT,
              file_ext       TEXT,
              size_bytes     INTEGER,
              mtime_ns       INTEGER,
              sha256         TEXT,
              title          TEXT,
              tags_json      TEXT,
              metadata_json  TEXT,
              discovered_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              status         TEXT NOT NULL DEFAULT 'active',
              change_count   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS documentation_changes (
              change_id     INTEGER PRIMARY KEY AUTOINCREMENT,
              doc_id        TEXT NOT NULL,
              change_type   TEXT NOT NULL,
              sha256        TEXT,
              size_bytes    INTEGER,
              mtime_ns      INTEGER,
              description   TEXT,
              context       TEXT,
              recorded_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS documentation_sections (
              section_id       TEXT PRIMARY KEY,
              doc_id           TEXT NOT NULL,
              parent_section_id TEXT,
              order_index      INTEGER NOT NULL,
              title            TEXT NOT NULL,
              anchor           TEXT,
              byte_start       INTEGER,
              byte_end         INTEGER,
              token_start      INTEGER,
              token_end        INTEGER,
              summary          TEXT,
              last_synced_at   TEXT,
              source_version   TEXT,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE,
              FOREIGN KEY(parent_section_id) REFERENCES documentation_sections(section_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_documentation_sections_doc
              ON documentation_sections(doc_id);

            CREATE INDEX IF NOT EXISTS idx_documentation_sections_parent
              ON documentation_sections(parent_section_id);

            CREATE TABLE IF NOT EXISTS documentation_excerpts (
              excerpt_id    TEXT PRIMARY KEY,
              doc_id        TEXT NOT NULL,
              section_id    TEXT,
              content       TEXT NOT NULL,
              justification TEXT,
              token_length  INTEGER,
              embedding_id  TEXT,
              created_at    TEXT NOT NULL,
              updated_at    TEXT NOT NULL,
              source_version TEXT,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE,
              FOREIGN KEY(section_id) REFERENCES documentation_sections(section_id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_documentation_excerpts_doc
              ON documentation_excerpts(doc_id);

            CREATE INDEX IF NOT EXISTS idx_documentation_excerpts_section
              ON documentation_excerpts(section_id);

            CREATE TABLE IF NOT EXISTS documentation_summaries (
              doc_id           TEXT PRIMARY KEY,
              summary_short    TEXT,
              summary_long     TEXT,
              key_points_json  TEXT,
              keywords_json    TEXT,
              embedding_id     TEXT,
              last_generated_at TEXT,
              generator_source TEXT,
              source_version   TEXT,
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS documentation_index_state (
              doc_id        TEXT NOT NULL,
              surface       TEXT NOT NULL,
              indexed_at    TEXT,
              status        TEXT,
              usage_score   REAL,
              metadata_json TEXT,
              PRIMARY KEY (doc_id, surface),
              FOREIGN KEY(doc_id) REFERENCES documentation(doc_id) ON DELETE CASCADE
            );
            """
        )

        self._ensure_search_schema(conn)

    def _ensure_search_schema(self, conn: sqlite3.Connection) -> None:
        expected_columns = ("doc_id", "section_id", "surface", "content", "updated_at")
        try:
            columns = conn.execute("PRAGMA table_info(documentation_search);").fetchall()
            column_names = tuple(row[1] for row in columns)
        except sqlite3.Error:
            column_names = ()
        if column_names != expected_columns:
            conn.execute("DROP TABLE IF EXISTS documentation_search;")
            conn.execute(
                """
                CREATE VIRTUAL TABLE documentation_search
                  USING fts5(
                    doc_id UNINDEXED,
                    section_id UNINDEXED,
                    surface,
                    content,
                    updated_at UNINDEXED,
                    tokenize = 'unicode61'
                  );
                """
            )

    # -- Public API -----------------------------------------------------

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        self._apply_pragmas(conn)
        self._ensure_schema(conn)

    def bulk_upsert(self, documents: Sequence[DocumentInput]) -> None:
        if not documents:
            return
        now = _iso_now()
        with self._connect() as conn:
            self._apply_pragmas(conn)
            for doc in documents:
                self._upsert_single(conn, doc, now)

    def replace_sections_bulk(
        self,
        sections: Dict[str, Sequence[SectionInput]],
    ) -> None:
        if not sections:
            return
        with self._connect() as conn:
            self._apply_pragmas(conn)
            for doc_id, entries in sections.items():
                conn.execute(
                    "DELETE FROM documentation_sections WHERE doc_id = ?;",
                    (doc_id,),
                )
                if not entries:
                    continue
                conn.executemany(
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
                    ) VALUES (
                      :section_id,
                      :doc_id,
                      :parent_section_id,
                      :order_index,
                      :title,
                      :anchor,
                      :byte_start,
                      :byte_end,
                      :token_start,
                      :token_end,
                      :summary,
                      :last_synced_at,
                      :source_version
                    );
                    """,
                    [
                        {
                            "section_id": entry.section_id,
                            "doc_id": entry.doc_id,
                            "parent_section_id": entry.parent_section_id,
                            "order_index": entry.order_index,
                            "title": entry.title,
                            "anchor": entry.anchor,
                            "byte_start": entry.byte_start,
                            "byte_end": entry.byte_end,
                            "token_start": entry.token_start,
                            "token_end": entry.token_end,
                            "summary": entry.summary,
                            "last_synced_at": entry.last_synced_at,
                            "source_version": entry.source_version,
                        }
                        for entry in entries
                    ],
                )

    def replace_search_entries(
        self,
        entries: Dict[str, Sequence[SearchEntry]],
    ) -> None:
        if not entries:
            return
        with self._connect() as conn:
            self._apply_pragmas(conn)
            self._ensure_schema(conn)
            for doc_id, doc_entries in entries.items():
                conn.execute(
                    "DELETE FROM documentation_search WHERE doc_id = ?;",
                    (doc_id,),
                )
                if not doc_entries:
                    continue
                conn.executemany(
                    """
                    INSERT INTO documentation_search (
                      doc_id,
                      section_id,
                      surface,
                      content,
                      updated_at
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    [
                        (
                            entry.doc_id,
                            entry.section_id,
                            entry.surface,
                            entry.content,
                            entry.updated_at or _iso_now(),
                        )
                        for entry in doc_entries
                    ],
                )
            conn.commit()

    def fetch_all(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM documentation
                WHERE status = 'active'
                ORDER BY doc_id;
                """
            ).fetchall()
        results: List[Dict[str, object]] = []
        for row in rows:
            metadata: Optional[dict]
            tags: List[str]
            tags_raw = row["tags_json"]
            metadata_raw = row["metadata_json"]
            try:
                tags = json.loads(tags_raw) if tags_raw else []
            except json.JSONDecodeError:
                tags = []
            try:
                metadata = json.loads(metadata_raw) if metadata_raw else None
            except json.JSONDecodeError:
                metadata = None
            results.append(
                {
                    "doc_id": row["doc_id"],
                    "doc_type": row["doc_type"],
                    "source_path": row["source_path"],
                    "staging_path": row["staging_path"],
                    "rel_path": row["rel_path"],
                    "file_name": row["file_name"],
                    "file_ext": row["file_ext"],
                    "size_bytes": row["size_bytes"],
                    "mtime_ns": row["mtime_ns"],
                    "sha256": row["sha256"],
                    "title": row["title"],
                    "tags": tags,
                    "metadata": metadata,
                    "status": row["status"],
                    "change_count": row["change_count"],
                    "discovered_at": row["discovered_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return results

    def fetch_sections(self, doc_ids: Sequence[str]) -> Dict[str, List[Dict[str, object]]]:
        doc_ids = [doc_id for doc_id in doc_ids if doc_id]
        if not doc_ids:
            return {}
        placeholders = ",".join("?" for _ in doc_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT doc_id,
                       section_id,
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
                FROM documentation_sections
                WHERE doc_id IN ({placeholders})
                ORDER BY doc_id, order_index;
                """,
                tuple(doc_ids),
            ).fetchall()
        results: Dict[str, List[Dict[str, object]]] = {doc_id: [] for doc_id in doc_ids}
        for row in rows:
            results.setdefault(row["doc_id"], []).append(
                {
                    "doc_id": row["doc_id"],
                    "section_id": row["section_id"],
                    "parent_section_id": row["parent_section_id"],
                    "order_index": row["order_index"],
                    "title": row["title"],
                    "anchor": row["anchor"],
                    "byte_start": row["byte_start"],
                    "byte_end": row["byte_end"],
                    "token_start": row["token_start"],
                    "token_end": row["token_end"],
                    "summary": row["summary"],
                    "last_synced_at": row["last_synced_at"],
                    "source_version": row["source_version"],
                }
            )
        return results

    def mark_inactive_except(self, active_ids: Iterable[str]) -> None:
        ids = {doc_id for doc_id in active_ids if doc_id}
        now = _iso_now()
        with self._connect() as conn:
            self._apply_pragmas(conn)
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"""
                    UPDATE documentation
                    SET status = 'archived',
                        updated_at = ?,
                        change_count = change_count + 1
                    WHERE status != 'archived'
                      AND doc_id NOT IN ({placeholders});
                    """,
                    (now, *ids),
                )
            else:
                conn.execute(
                    """
                    UPDATE documentation
                    SET status = 'archived',
                        updated_at = ?,
                        change_count = change_count + 1
                    WHERE status != 'archived';
                    """,
                    (now,),
                )

    def update_index_state(
        self,
        doc_id: str,
        surface: str,
        *,
        status: str = "ready",
        usage_score: Optional[float] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> None:
        indexed_at = _iso_now()
        metadata_json = json.dumps(metadata, sort_keys=True) if metadata else None
        with self._connect() as conn:
            self._apply_pragmas(conn)
            self._ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO documentation_index_state (
                  doc_id,
                  surface,
                  indexed_at,
                  status,
                  usage_score,
                  metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id, surface) DO UPDATE SET
                  indexed_at = excluded.indexed_at,
                  status = excluded.status,
                  usage_score = excluded.usage_score,
                  metadata_json = excluded.metadata_json;
                """,
                (doc_id, surface, indexed_at, status, usage_score, metadata_json),
            )
            conn.commit()

    def sync_scan(self, project_root: Path, scan_tsv: Path) -> None:
        project_root = project_root.resolve()
        documents: List[DocumentInput] = []
        seen_ids: List[str] = []
        if not scan_tsv.exists():
            return
        with scan_tsv.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                raw_path = (row.get("path") or "").strip()
                if not raw_path:
                    continue
                path = Path(raw_path)
                if not path.is_absolute():
                    path = (project_root / raw_path).resolve()
                if not _is_file(path):
                    continue
                doc_id = _stable_doc_id(path)
                raw_category = row.get("category") or row.get("type") or "document"
                doc_category = str(raw_category).strip() or "document"
                doc_type = doc_category.split("_", 1)[0] or doc_category
                rel_path: Optional[str]
                try:
                    rel_path = str(path.relative_to(project_root))
                except ValueError:
                    rel_path = str(path)
                stat = None
                try:
                    stat = path.stat()
                except OSError:
                    pass
                size_bytes = int(stat.st_size) if stat else None
                mtime_ns = int(
                    getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
                ) if stat else None
                sha = _sha256(path)
                score = _safe_int(row.get("score"))
                confidence = _safe_float(row.get("confidence"))
                tags = _normalize_tags(
                    [doc_category] + (doc_category.replace("-", "_").split("_"))
                )
                metadata: Dict[str, object] = {
                    "discovery_category": doc_category,
                }
                if score is not None:
                    metadata["discovery_score"] = score
                if confidence is not None:
                    metadata["discovery_confidence"] = confidence
                    if score is None:
                        metadata["discovery_score"] = int(confidence * 100)
                documents.append(
                    DocumentInput(
                        doc_id=doc_id,
                        doc_type=doc_type,
                        source_path=str(path),
                        staging_path=str(path)
                        if ".gpt-creator" in path.parts
                        else None,
                        rel_path=rel_path,
                        title=path.stem.replace("_", " ").replace("-", " ").title(),
                        size_bytes=size_bytes,
                        mtime_ns=mtime_ns,
                        sha256=sha,
                        tags=tags,
                        metadata=metadata,
                        context="scan",
                        file_name=path.name,
                        file_ext=path.suffix.lstrip(".").lower() or None,
                    )
                )
                seen_ids.append(doc_id)
        if documents:
            self.bulk_upsert(documents)
        self.mark_inactive_except(seen_ids)

    def upsert_summaries(self, summaries: Sequence[SummaryInput]) -> None:
        if not summaries:
            return
        with self._connect() as conn:
            self._apply_pragmas(conn)
            for entry in summaries:
                key_points_json = json.dumps(list(entry.key_points), ensure_ascii=False)
                keywords_json = json.dumps(list(entry.keywords), ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO documentation_summaries (
                      doc_id,
                      summary_short,
                      summary_long,
                      key_points_json,
                      keywords_json,
                      embedding_id,
                      last_generated_at,
                      generator_source,
                      source_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_id) DO UPDATE SET
                      summary_short = excluded.summary_short,
                      summary_long = excluded.summary_long,
                      key_points_json = excluded.key_points_json,
                      keywords_json = excluded.keywords_json,
                      last_generated_at = excluded.last_generated_at,
                      generator_source = excluded.generator_source,
                      source_version = excluded.source_version,
                      embedding_id = CASE
                        WHEN documentation_summaries.source_version != excluded.source_version
                          THEN excluded.embedding_id
                        WHEN excluded.embedding_id IS NOT NULL
                          THEN excluded.embedding_id
                        ELSE documentation_summaries.embedding_id
                      END;
                    """,
                    (
                        entry.doc_id,
                        entry.summary_short,
                        entry.summary_long,
                        key_points_json,
                        keywords_json,
                        entry.embedding_id,
                        entry.last_generated_at or _iso_now(),
                        entry.generator_source,
                        entry.source_version,
                    ),
                )

    def replace_excerpts_bulk(
        self,
        excerpts: Dict[str, Sequence[ExcerptInput]],
    ) -> None:
        if not excerpts:
            return
        with self._connect() as conn:
            self._apply_pragmas(conn)
            for doc_id, items in excerpts.items():
                conn.execute(
                    "DELETE FROM documentation_excerpts WHERE doc_id = ?;",
                    (doc_id,),
                )
                if not items:
                    continue
                conn.executemany(
                    """
                    INSERT INTO documentation_excerpts (
                      excerpt_id,
                      doc_id,
                      section_id,
                      content,
                      justification,
                      token_length,
                      embedding_id,
                      created_at,
                      updated_at,
                      source_version
                    ) VALUES (
                      :excerpt_id,
                      :doc_id,
                      :section_id,
                      :content,
                      :justification,
                      :token_length,
                      :embedding_id,
                      :created_at,
                      :updated_at,
                      :source_version
                    );
                    """,
                    [
                        {
                            "excerpt_id": item.excerpt_id,
                            "doc_id": item.doc_id,
                            "section_id": item.section_id,
                            "content": item.content,
                            "justification": item.justification,
                            "token_length": item.token_length,
                            "embedding_id": item.embedding_id,
                            "created_at": item.created_at or _iso_now(),
                            "updated_at": item.updated_at or _iso_now(),
                            "source_version": item.source_version,
                        }
                        for item in items
                    ],
                )

    # -- Internal helpers ------------------------------------------------

    def _upsert_single(
        self,
        conn: sqlite3.Connection,
        doc: DocumentInput,
        now: str,
    ) -> None:
        normalized_tags = _normalize_tags(doc.tags)
        metadata_payload: Dict[str, object] = {}
        if doc.metadata:
            metadata_payload.update(doc.metadata)
        if doc.context:
            metadata_payload.setdefault("_context", doc.context)
        tags_json = json.dumps(normalized_tags) if normalized_tags else None
        metadata_json = json.dumps(metadata_payload) if metadata_payload else None
        file_name = doc.file_name
        if not file_name:
            for candidate in (doc.staging_path, doc.source_path, doc.rel_path):
                if candidate:
                    file_name = Path(candidate).name
                    break
        file_ext = doc.file_ext or (
            Path(file_name).suffix.lstrip(".").lower() if file_name else None
        )
        size_bytes = doc.size_bytes if doc.size_bytes is not None else None
        mtime_ns = doc.mtime_ns if doc.mtime_ns is not None else None
        sha256 = doc.sha256 if doc.sha256 else None

        existing = conn.execute(
            """
            SELECT sha256, size_bytes, mtime_ns, tags_json, metadata_json,
                   title, status, change_count
            FROM documentation
            WHERE doc_id = ?;
            """,
            (doc.doc_id,),
        ).fetchone()

        changed = False
        change_count = 0
        status = doc.status or "active"
        if existing:
            change_count = existing["change_count"] or 0
            if status != existing["status"]:
                changed = True
            else:
                if sha256 and sha256 != existing["sha256"]:
                    changed = True
                if size_bytes is not None and size_bytes != existing["size_bytes"]:
                    changed = True
                if mtime_ns is not None and mtime_ns != existing["mtime_ns"]:
                    changed = True
                if tags_json != existing["tags_json"]:
                    changed = True
                if metadata_json != existing["metadata_json"]:
                    changed = True
                if (doc.title or "") != (existing["title"] or ""):
                    changed = True
            if changed:
                change_count += 1
            conn.execute(
                """
                UPDATE documentation
                SET doc_type     = ?,
                    source_path  = ?,
                    staging_path = ?,
                    rel_path     = ?,
                    file_name    = ?,
                    file_ext     = ?,
                    size_bytes   = ?,
                    mtime_ns     = ?,
                    sha256       = ?,
                    title        = ?,
                    tags_json    = ?,
                    metadata_json = ?,
                    status       = ?,
                    change_count = ?,
                    updated_at   = ?
                WHERE doc_id = ?;
                """,
                (
                    doc.doc_type,
                    doc.source_path,
                    doc.staging_path,
                    doc.rel_path,
                    file_name,
                    file_ext,
                    size_bytes,
                    mtime_ns,
                    sha256,
                    doc.title,
                    tags_json,
                    metadata_json,
                    status,
                    change_count,
                    now,
                    doc.doc_id,
                ),
            )
            if changed:
                self._record_change(
                    conn,
                    doc_id=doc.doc_id,
                    change_type="update",
                    sha256=sha256,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    description="documentation row updated",
                    context=doc.context,
                )
        else:
            conn.execute(
                """
                INSERT INTO documentation (
                  doc_id,
                  doc_type,
                  source_path,
                  staging_path,
                  rel_path,
                  file_name,
                  file_ext,
                  size_bytes,
                  mtime_ns,
                  sha256,
                  title,
                  tags_json,
                  metadata_json,
                  discovered_at,
                  updated_at,
                  status,
                  change_count
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                );
                """,
                (
                    doc.doc_id,
                    doc.doc_type,
                    doc.source_path,
                    doc.staging_path,
                    doc.rel_path,
                    file_name,
                    file_ext,
                    size_bytes,
                    mtime_ns,
                    sha256,
                    doc.title,
                    tags_json,
                    metadata_json,
                    now,
                    now,
                    status,
                    0,
                ),
            )
            self._record_change(
                conn,
                doc_id=doc.doc_id,
                change_type="insert",
                sha256=sha256,
                size_bytes=size_bytes,
                mtime_ns=mtime_ns,
                description="documentation row inserted",
                context=doc.context,
            )

        surface = (
            doc.title
            or doc.rel_path
            or file_name
            or doc.source_path
            or doc.doc_id
        )
        conn.execute(
            "DELETE FROM documentation_search WHERE doc_id = ?;",
            (doc.doc_id,),
        )
        conn.execute(
            """
            INSERT INTO documentation_search (
              doc_id,
              section_id,
              surface,
              content,
              updated_at
            ) VALUES (?, NULL, ?, ?, ?);
            """,
            (doc.doc_id, surface, surface, now),
        )

    @staticmethod
    def _record_change(
        conn: sqlite3.Connection,
        *,
        doc_id: str,
        change_type: str,
        sha256: Optional[str],
        size_bytes: Optional[int],
        mtime_ns: Optional[int],
        description: Optional[str],
        context: Optional[str],
    ) -> None:
        conn.execute(
            """
            INSERT INTO documentation_changes (
              doc_id,
              change_type,
              sha256,
              size_bytes,
              mtime_ns,
              description,
              context,
              recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                doc_id,
                change_type,
                sha256,
                size_bytes,
                mtime_ns,
                description,
                context,
                _iso_now(),
            ),
        )


def _registry_db_path(runtime_dir: Path) -> Path:
    return runtime_dir / "staging" / "plan" / "tasks" / "tasks.db"


def _db_path_from_runtime(runtime_dir: Optional[str]) -> Path:
    if runtime_dir:
        return _registry_db_path(Path(runtime_dir).expanduser())
    env_path = os.environ.get("GC_DOCUMENTATION_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path(".gpt-creator/staging/plan/tasks/tasks.db")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc_registry",
        description="Documentation registry utilities.",
        add_help=True,
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser(
        "register",
        help="Record a documentation change in the registry.",
        add_help=True,
        allow_abbrev=False,
    )
    register_parser.add_argument(
        "--runtime-dir",
        default=None,
        help="Runtime directory containing the tasks catalog (fallbacks to GC_DOCUMENTATION_DB_PATH).",
    )
    register_parser.add_argument(
        "doc_id",
        nargs="?",
        help="Document identifier (required to log a change).",
    )
    register_parser.add_argument(
        "path",
        nargs="?",
        help="Path to the updated document or section.",
    )
    register_parser.add_argument(
        "summary",
        nargs="?",
        default="",
        help="Short summary describing the change.",
    )

    search_parser = subparsers.add_parser(
        "search",
        help="Query the documentation FTS index.",
        add_help=True,
        allow_abbrev=False,
    )
    search_parser.add_argument(
        "query",
        help="FTS5 query (e.g. \"lockout\" OR \"audit\").",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="Maximum number of rows to return (default: 12).",
    )
    search_parser.add_argument(
        "--runtime-dir",
        default=None,
        help="Runtime directory containing the documentation catalog (fallbacks to GC_DOCUMENTATION_DB_PATH).",
    )

    sync_parser = subparsers.add_parser(
        "sync-scan",
        help="Ingest discovery TSV output from `gpt-creator scan`.",
        add_help=True,
        allow_abbrev=False,
    )
    sync_parser.add_argument(
        "--project-root",
        required=True,
        help="Absolute path to the project root.",
    )
    sync_parser.add_argument(
        "--runtime-dir",
        required=True,
        help="Path to the .gpt-creator runtime directory.",
    )
    sync_parser.add_argument(
        "--scan-tsv",
        required=True,
        help="Path to the discovery TSV produced by `gpt-creator scan`.",
    )

    return parser


def _handle_register(args: argparse.Namespace) -> int:
    doc_id = getattr(args, "doc_id", None)
    if not doc_id:
        print("doc_registry: register OK (compatibility shim).", flush=True)
        return 0

    path_arg = getattr(args, "path", None)
    if not path_arg:
        print("doc_registry: register requires DOC_ID and PATH arguments.", file=sys.stderr)
        return 2

    summary = getattr(args, "summary", "") or ""
    db_path = _db_path_from_runtime(getattr(args, "runtime_dir", None))

    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("SELECT 1 FROM documentation_changes LIMIT 1;")
            conn.execute(
                "INSERT INTO documentation_changes(doc_id, path, summary, changed_at) VALUES(?,?,?,?)",
                (doc_id, path_arg, summary, int(time.time())),
            )
            conn.commit()
            print("registered", flush=True)
            return 0
    except sqlite3.OperationalError as exc:
        print(f"documentation_changes table missing in {db_path}: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"doc_registry: failed to record change ({exc}).", file=sys.stderr)
        return 2


def _handle_sync_scan(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).expanduser()
    runtime_dir = Path(args.runtime_dir).expanduser()
    scan_tsv = Path(args.scan_tsv).expanduser()
    db_path = _registry_db_path(runtime_dir)
    registry = DocRegistry(db_path)
    registry.sync_scan(project_root, scan_tsv)
    print(f"doc_registry: synced discovery from {scan_tsv}", flush=True)
    return 0


def _handle_search(args: argparse.Namespace) -> int:
    db_path = _db_path_from_runtime(getattr(args, "runtime_dir", None))
    limit = getattr(args, "limit", 12) or 12
    if limit < 1:
        limit = 1
    try:
        with sqlite3.connect(str(db_path)) as conn:
            for doc_id, surface in conn.execute(
                """
                SELECT doc_id, substr(surface, 1, 200)
                FROM documentation_search
                WHERE documentation_search MATCH ?
                LIMIT ?
                """,
                (args.query, limit),
            ):
                print(f"{doc_id} | {surface}")
        return 0
    except sqlite3.Error as exc:
        print(f"doc_registry: search failed ({exc}).", file=sys.stderr)
        return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "register":
        return _handle_register(args)
    if args.command == "search":
        return _handle_search(args)
    if args.command == "sync-scan":
        return _handle_sync_scan(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
