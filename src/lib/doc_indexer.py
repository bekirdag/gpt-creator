#!/usr/bin/env python3
"""
Indexing utilities for the documentation catalog.

Provides a cohesive layer that:

- Populates SQLite FTS tables for keyword search.
- Manages a lightweight local vector index for semantic retrieval.
- Tracks index freshness in the documentation registry metadata tables.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import argparse

from .doc_registry import DocRegistry, SearchEntry


def _iso_ts_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    approx = int(len(text.split()) * 1.3)
    return max(1, approx)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _normalise_whitespace(value: str) -> str:
    return " ".join(value.split())


@dataclass
class VectorTask:
    embedding_id: str
    doc_id: str
    section_id: Optional[str]
    surface: str
    text: str
    source_version: Optional[str]
    metadata: Dict[str, Optional[str]]


@dataclass
class VectorRecord:
    embedding_id: str
    doc_id: str
    section_id: Optional[str]
    surface: str
    vector: Sequence[float]
    source_version: Optional[str]
    metadata: Dict[str, Optional[str]]


class EmbeddingProvider:
    """Interface for embedding providers."""

    def embed(self, texts: Sequence[str], *, model: Optional[str] = None) -> Sequence[Sequence[float]]:
        raise NotImplementedError


class HashEmbeddingProvider(EmbeddingProvider):
    """
    Offline-friendly embedding provider that produces deterministic vectors using hashing.

    Useful for development and testing when external embedding APIs are not available.
    Vectors are normalised to unit length for rough cosine similarity behaviour.
    """

    def __init__(self, dims: int = 256) -> None:
        self.dims = max(32, dims)

    def embed(self, texts: Sequence[str], *, model: Optional[str] = None) -> Sequence[Sequence[float]]:
        return [self._vector_from_text(text) for text in texts]

    def _vector_from_text(self, text: str) -> Sequence[float]:
        digest = hashlib.sha256(text.encode("utf-8", "replace")).digest()
        values: List[float] = []
        seed = digest
        while len(values) < self.dims:
            for idx in range(0, len(seed), 4):
                if len(values) >= self.dims:
                    break
                chunk = seed[idx : idx + 4]
                val = int.from_bytes(chunk, "big", signed=False)
                values.append((val % 1000) / 1000.0)
            seed = hashlib.sha256(seed).digest()
        norm = math.sqrt(sum(val * val for val in values)) or 1.0
        return [val / norm for val in values]


class LocalVectorIndex:
    """
    Lightweight vector index backed by SQLite.

    Stores embedding vectors as JSON arrays along with metadata for freshness checks.
    This keeps the indexing pipeline deterministic without introducing heavyweight dependencies.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vectors (
              embedding_id TEXT PRIMARY KEY,
              doc_id TEXT NOT NULL,
              section_id TEXT,
              surface TEXT NOT NULL,
              vector_json TEXT NOT NULL,
              dims INTEGER NOT NULL,
              source_version TEXT,
              metadata_json TEXT,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_doc ON vectors(doc_id)"
        )

    def get(self, embedding_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT * FROM vectors WHERE embedding_id = ?",
                (embedding_id,),
            ).fetchone()
            if row is None:
                return None
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            vector = json.loads(row["vector_json"])
            return {
                "embedding_id": row["embedding_id"],
                "doc_id": row["doc_id"],
                "section_id": row["section_id"],
                "surface": row["surface"],
                "vector": vector,
                "dims": row["dims"],
                "source_version": row["source_version"],
                "metadata": metadata,
                "updated_at": row["updated_at"],
            }

    def upsert(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        with self._connect() as conn:
            self._ensure_schema(conn)
            now = _iso_ts_now()
            payloads = [
                (
                    record.embedding_id,
                    record.doc_id,
                    record.section_id,
                    record.surface,
                    json.dumps(list(record.vector)),
                    len(record.vector),
                    record.source_version,
                    json.dumps(record.metadata, sort_keys=True),
                    now,
                )
                for record in records
            ]
            conn.executemany(
                """
                INSERT INTO vectors (
                  embedding_id,
                  doc_id,
                  section_id,
                  surface,
                  vector_json,
                  dims,
                  source_version,
                  metadata_json,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(embedding_id) DO UPDATE SET
                  doc_id = excluded.doc_id,
                  section_id = excluded.section_id,
                  surface = excluded.surface,
                  vector_json = excluded.vector_json,
                  dims = excluded.dims,
                  source_version = excluded.source_version,
                  metadata_json = excluded.metadata_json,
                  updated_at = excluded.updated_at
                """,
                payloads,
            )
            conn.commit()

    def delete_for_docs(self, doc_ids: Sequence[str]) -> None:
        if not doc_ids:
            return
        with self._connect() as conn:
            self._ensure_schema(conn)
            conn.executemany(
                "DELETE FROM vectors WHERE doc_id = ?",
                ((doc_id,) for doc_id in doc_ids),
            )
            conn.commit()


class DocIndexer:
    def __init__(
        self,
        db_path: Path,
        *,
        vector_index: Optional[LocalVectorIndex] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        embedding_model: Optional[str] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.registry = DocRegistry(self.db_path)
        default_index_path = self.db_path.parent / "documentation-vector-index.sqlite"
        self.vector_index = vector_index or LocalVectorIndex(default_index_path)
        self.embedding_provider = embedding_provider or HashEmbeddingProvider()
        self.embedding_model = embedding_model or "hash://embedding"

    def rebuild_full_text(self, doc_ids: Optional[Sequence[str]] = None) -> None:
        docs, summaries, excerpts = self._load_catalog_rows(doc_ids)
        entries_map: Dict[str, List[SearchEntry]] = {}
        metadata_map: Dict[str, Dict[str, object]] = {}

        for doc_id, doc in docs.items():
            summary = summaries.get(doc_id)
            doc_entries: List[SearchEntry] = []
            text_parts: List[str] = []
            doc_updated_at_raw = doc.get("updated_at")
            doc_updated_at = (
                doc_updated_at_raw
                if isinstance(doc_updated_at_raw, str) and doc_updated_at_raw
                else _iso_ts_now()
            )
            if doc.get("title"):
                text_parts.append(doc["title"])
            if doc.get("rel_path"):
                text_parts.append(doc["rel_path"])
            tags = doc.get("tags_json")
            if tags:
                try:
                    tag_list = json.loads(tags)
                    if tag_list:
                        text_parts.append("Tags: " + ", ".join(tag_list))
                except Exception:
                    text_parts.append(f"Tags: {tags}")
            if summary:
                if summary.get("summary_short"):
                    text_parts.append(summary["summary_short"])
                if summary.get("summary_long"):
                    text_parts.append(summary["summary_long"])
                key_points = summary.get("key_points_json")
                if key_points:
                    try:
                        points = json.loads(key_points) or []
                    except Exception:
                        points = []
                    if points:
                        text_parts.append("Key Points: " + " | ".join(points))
                keywords = summary.get("keywords_json")
                if keywords:
                    try:
                        kw = json.loads(keywords) or []
                    except Exception:
                        kw = []
                    if kw:
                        text_parts.append("Keywords: " + ", ".join(kw))
            if doc.get("metadata_json"):
                text_parts.append(doc["metadata_json"])
            combined = _normalise_whitespace("\n".join(part for part in text_parts if part))
            if combined:
                doc_entries.append(
                    SearchEntry(
                        doc_id=doc_id,
                        section_id=None,
                        surface="document",
                        content=combined,
                        updated_at=doc_updated_at,
                    )
                )

            excerpt_rows = excerpts.get(doc_id, [])
            for row in excerpt_rows:
                content = row.get("content") or ""
                justification = row.get("justification")
                extra = f"\nWhy it matters: {justification}" if justification else ""
                full = _normalise_whitespace(content + extra)
                if not full:
                    continue
                excerpt_updated_at_raw = row.get("updated_at")
                excerpt_updated_at = (
                    excerpt_updated_at_raw
                    if isinstance(excerpt_updated_at_raw, str) and excerpt_updated_at_raw
                    else doc_updated_at
                )
                doc_entries.append(
                    SearchEntry(
                        doc_id=doc_id,
                        section_id=row.get("section_id"),
                        surface="excerpt",
                        content=full,
                        updated_at=excerpt_updated_at,
                    )
                )

            if doc_entries:
                entries_map[doc_id] = doc_entries
                metadata_map[doc_id] = {
                    "surfaces": sorted({entry.surface for entry in doc_entries}),
                    "entry_count": len(doc_entries),
                }

        if entries_map:
            self.registry.replace_search_entries(entries_map)
            for doc_id, meta in metadata_map.items():
                self.registry.update_index_state(
                    doc_id,
                    "fts",
                    metadata=meta,
                )

    def rebuild_vector_index(
        self,
        doc_ids: Optional[Sequence[str]] = None,
        *,
        batch_size: int = 16,
    ) -> None:
        docs, summaries, excerpts = self._load_catalog_rows(doc_ids)
        tasks: List[VectorTask] = []
        summary_updates: List[Tuple[str, str]] = []
        excerpt_updates: List[Tuple[str, str]] = []
        for doc_id, summary in summaries.items():
            summary_text_parts: List[str] = []
            if summary.get("summary_long"):
                summary_text_parts.append(summary["summary_long"])
            elif summary.get("summary_short"):
                summary_text_parts.append(summary["summary_short"])
            key_points = summary.get("key_points_json")
            if key_points:
                try:
                    points = json.loads(key_points) or []
                except Exception:
                    points = []
                summary_text_parts.extend(points)
            text = _normalise_whitespace("\n".join(part for part in summary_text_parts if part))
            if not text:
                continue
            embedding_id = summary.get("embedding_id") or f"{doc_id}:summary"
            if not summary.get("embedding_id"):
                summary_updates.append((embedding_id, doc_id))
            task = VectorTask(
                embedding_id=embedding_id,
                doc_id=doc_id,
                section_id=None,
                surface="summary",
                text=text,
                source_version=summary.get("source_version"),
                metadata={
                    "doc_id": doc_id,
                    "surface": "summary",
                    "token_estimate": summary.get("token_estimate"),
                },
            )
            if self._needs_embedding(task):
                tasks.append(task)

        for doc_id, rows in excerpts.items():
            for row in rows:
                text = _normalise_whitespace(row.get("content") or "")
                if not text:
                    continue
                embedding_id = row.get("embedding_id") or f"{doc_id}:excerpt:{row.get('excerpt_id')}"
                if not row.get("embedding_id"):
                    excerpt_updates.append((embedding_id, row["excerpt_id"]))
                task = VectorTask(
                    embedding_id=embedding_id,
                    doc_id=doc_id,
                    section_id=row.get("section_id"),
                    surface="excerpt",
                    text=text,
                    source_version=row.get("source_version"),
                    metadata={
                        "doc_id": doc_id,
                        "excerpt_id": row.get("excerpt_id"),
                        "token_length": row.get("token_length"),
                    },
                )
                if self._needs_embedding(task):
                    tasks.append(task)

        new_vectors: List[VectorRecord] = []
        for chunk_start in range(0, len(tasks), batch_size):
            chunk = tasks[chunk_start : chunk_start + batch_size]
            embeddings = self.embedding_provider.embed(
                [task.text for task in chunk],
                model=self.embedding_model,
            )
            for task, vector in zip(chunk, embeddings):
                metadata = dict(task.metadata)
                metadata["text_hash"] = _hash_text(task.text)
                metadata["token_estimate"] = _estimate_tokens(task.text)
                new_vectors.append(
                    VectorRecord(
                        embedding_id=task.embedding_id,
                        doc_id=task.doc_id,
                        section_id=task.section_id,
                        surface=task.surface,
                        vector=vector,
                        source_version=task.source_version,
                        metadata=metadata,
                    )
                )

        if new_vectors:
            self.vector_index.upsert(new_vectors)

        if summary_updates or excerpt_updates:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                self.registry.ensure_schema(conn)
                if summary_updates:
                    conn.executemany(
                        "UPDATE documentation_summaries SET embedding_id = ? WHERE doc_id = ?",
                        summary_updates,
                    )
                if excerpt_updates:
                    conn.executemany(
                        "UPDATE documentation_excerpts SET embedding_id = ? WHERE excerpt_id = ?",
                        excerpt_updates,
                    )
                conn.commit()

        for doc_id in docs.keys():
            existing_summary = summaries.get(doc_id)
            metadata = {
                "summary_vector": bool(existing_summary),
                "excerpt_vectors": len(excerpts.get(doc_id, [])),
            }
            self.registry.update_index_state(
                doc_id,
                "vector",
                metadata=metadata,
            )

    def _needs_embedding(self, task: VectorTask) -> bool:
        existing = self.vector_index.get(task.embedding_id)
        if existing is None:
            return True
        metadata = existing.get("metadata") or {}
        current_hash = _hash_text(task.text)
        if metadata.get("text_hash") != current_hash:
            return True
        if task.source_version and existing.get("source_version") != task.source_version:
            return True
        return False

    def _load_catalog_rows(
        self,
        doc_ids: Optional[Sequence[str]] = None,
    ) -> Tuple[Dict[str, Dict[str, object]], Dict[str, Dict[str, object]], Dict[str, List[Dict[str, object]]]]:
        doc_filter = ""
        params: List[str] = []
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            doc_filter = f"WHERE doc_id IN ({placeholders})"
            params.extend(doc_ids)

        docs: Dict[str, Dict[str, object]] = {}
        summaries: Dict[str, Dict[str, object]] = {}
        excerpts: Dict[str, List[Dict[str, object]]] = {}

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            self.registry.ensure_schema(conn)
            # Base document rows.
            for row in conn.execute(
                f"""
                SELECT doc_id, title, rel_path, tags_json, metadata_json, updated_at
                FROM documentation
                {doc_filter}
                """,
                params,
            ):
                docs[row["doc_id"]] = dict(row)

            if not docs:
                return (docs, summaries, excerpts)

            doc_ids_list = list(docs.keys())
            placeholders = ",".join("?" for _ in doc_ids_list)

            for row in conn.execute(
                f"""
                SELECT
                  doc_id,
                  summary_short,
                  summary_long,
                  key_points_json,
                  keywords_json,
                  embedding_id,
                  source_version
                FROM documentation_summaries
                WHERE doc_id IN ({placeholders})
                """,
                doc_ids_list,
            ):
                payload = dict(row)
                payload["token_estimate"] = _estimate_tokens(
                    " ".join(
                        filter(
                            None,
                            [
                                row["summary_short"] or "",
                                row["summary_long"] or "",
                            ],
                        )
                    )
                )
                summaries[row["doc_id"]] = payload

            for row in conn.execute(
                f"""
                SELECT
                  excerpt_id,
                  doc_id,
                  section_id,
                  content,
                  justification,
                  token_length,
                  embedding_id,
                  source_version,
                  updated_at
                FROM documentation_excerpts
                WHERE doc_id IN ({placeholders})
                ORDER BY
                  CASE WHEN token_length IS NULL THEN 1 ELSE 0 END,
                  token_length,
                  excerpt_id
                """,
                doc_ids_list,
            ):
                excerpt_payload = dict(row)
                excerpts.setdefault(row["doc_id"], []).append(excerpt_payload)

        return (docs, summaries, excerpts)


def _runtime_db_path(runtime_dir: Path) -> Path:
    return runtime_dir / "staging" / "plan" / "tasks" / "tasks.db"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage documentation indexes.")
    parser.add_argument("--runtime-dir", help="Runtime directory (e.g., .gpt-creator).")
    parser.add_argument("--doc-id", action="append", help="Limit operations to specific document IDs.")
    parser.add_argument("--skip-full-text", action="store_true", help="Skip rebuilding the FTS index.")
    parser.add_argument("--skip-vector", action="store_true", help="Skip rebuilding the vector index.")
    parser.add_argument("--check", action="store_true", help="Print index health summary and exit.")
    return parser


def _resolve_db_path(runtime_dir: Optional[str]) -> Path:
    if runtime_dir:
        return _runtime_db_path(Path(runtime_dir).expanduser())
    env_path = os.environ.get("GC_DOCUMENTATION_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path(".gpt-creator/staging/plan/tasks/tasks.db")


def _print_index_health(db_path: Path) -> int:
    try:
        with sqlite3.connect(str(db_path)) as conn:
            total_row = conn.execute("SELECT count(*) FROM documentation;").fetchone()
            fts_row = conn.execute("SELECT count(*) FROM documentation_search;").fetchone()
        total = total_row[0] if total_row else 0
        fts = fts_row[0] if fts_row else 0
        print(f"documentation rows={total}, documentation_search rows={fts}")
        return 0
    except sqlite3.Error as exc:
        print(f"Doc index check failed: {exc}", file=sys.stderr)
        return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.check:
        db_path = _resolve_db_path(args.runtime_dir)
        return _print_index_health(db_path)

    if not args.runtime_dir:
        parser.error("--runtime-dir is required when rebuilding indexes (use --check for health summary).")

    runtime_dir = Path(args.runtime_dir).resolve()
    db_path = _runtime_db_path(runtime_dir)
    indexer = DocIndexer(db_path)
    doc_ids = args.doc_id if args.doc_id else None
    if not args.skip_full_text:
        indexer.rebuild_full_text(doc_ids)
    if not args.skip_vector:
        indexer.rebuild_vector_index(doc_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
