#!/usr/bin/env python3
"""
Heuristic documentation pipeline that refreshes summaries, keywords, and excerpts.

This implementation avoids external dependencies so the catalog can stay in sync
whenever `gpt-creator scan` runs.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "have",
    "your",
    "will",
    "into",
    "about",
    "their",
    "there",
    "which",
    "should",
    "being",
    "such",
    "using",
    "when",
    "where",
    "while",
    "within",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runtime_db_path(runtime_dir: Path) -> Path:
    return runtime_dir / "staging" / "plan" / "tasks" / "tasks.db"


def _read_text(paths: Iterable[Optional[str]]) -> str:
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="latin-1")
            except OSError:
                continue
        except OSError:
            continue
    return ""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text.split()) * 1.3))


def _paragraphs(text: str) -> List[str]:
    items = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return items


def _generate_keywords(text: str, tags: Sequence[str], limit: int = 12) -> List[str]:
    tokens = re.findall(r"[A-Za-z0-9]{3,}", text.lower())
    counter = Counter(token for token in tokens if token not in STOPWORDS)
    keywords: List[str] = []
    keywords.extend(tag.lower() for tag in tags if tag)
    for token, _count in counter.most_common(limit * 2):
        if token in keywords:
            continue
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords[:limit]


def _load_sections(conn: sqlite3.Connection, doc_id: str) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT section_id, parent_section_id, title, order_index
            FROM documentation_sections
            WHERE doc_id = ?
            ORDER BY order_index
            """,
            (doc_id,),
        )
    )


def _extract_key_points(sections: Sequence[sqlite3.Row], limit: int = 5) -> List[str]:
    points: List[str] = []
    for row in sections:
        title = (row["title"] or "").strip()
        if not title:
            continue
        if row["parent_section_id"] is None:
            # Skip synthetic root.
            continue
        points.append(title)
        if len(points) >= limit:
            break
    return points


def _select_excerpts(paragraphs: Sequence[str], limit: int = 5) -> List[str]:
    excerpts: List[str] = []
    for para in paragraphs:
        if 40 <= len(para) <= 800:
            excerpts.append(para)
        elif len(para) > 800:
            excerpts.append(para[:800].rstrip() + "…")
        if len(excerpts) >= limit:
            break
    return excerpts


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
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
          source_version TEXT
        )
        """
    )
    conn.execute(
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
          source_version TEXT
        )
        """
    )


def run_pipeline(project_root: Path, runtime_dir: Path) -> None:
    db_path = _runtime_db_path(runtime_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_tables(conn)
        docs = conn.execute(
            """
            SELECT doc_id, source_path, staging_path, title, tags_json, sha256
            FROM documentation
            WHERE status = 'active'
            """
        ).fetchall()
        now = _iso_now()
        for doc in docs:
            doc_id = doc["doc_id"]
            tags = []
            if doc["tags_json"]:
                try:
                    tags = json.loads(doc["tags_json"])
                except Exception:
                    tags = []
            text = _read_text([doc["staging_path"], doc["source_path"]])
            clean_text = text.strip()
            if not clean_text:
                continue
            paragraphs = _paragraphs(clean_text)
            preview = " ".join(paragraphs[:3]) if paragraphs else clean_text
            summary_short = _truncate(clean_text.replace("\n", " "), 300)
            summary_long = _truncate(preview.replace("\n", " "), 1200)

            sections = _load_sections(conn, doc_id)
            key_points = _extract_key_points(sections)
            keywords = _generate_keywords(clean_text, tags)

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
                VALUES (?, ?, ?, ?, ?, NULL, ?, 'heuristic', ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                  summary_short = excluded.summary_short,
                  summary_long = excluded.summary_long,
                  key_points_json = excluded.key_points_json,
                  keywords_json = excluded.keywords_json,
                  last_generated_at = excluded.last_generated_at,
                  generator_source = excluded.generator_source,
                  source_version = excluded.source_version,
                  embedding_id = CASE
                    WHEN documentation_summaries.source_version != excluded.source_version THEN NULL
                    ELSE documentation_summaries.embedding_id
                  END
                """,
                (
                    doc_id,
                    summary_short,
                    summary_long,
                    json.dumps(key_points, ensure_ascii=False),
                    json.dumps(keywords, ensure_ascii=False),
                    now,
                    doc["sha256"],
                ),
            )

            conn.execute(
                "DELETE FROM documentation_excerpts WHERE doc_id = ?",
                (doc_id,),
            )
            excerpts = _select_excerpts(paragraphs)
            for content in excerpts:
                excerpt_id = str(uuid.uuid4())
                conn.execute(
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
                    )
                    VALUES (?, ?, NULL, ?, NULL, ?, NULL, ?, ?, ?)
                    """,
                    (
                        excerpt_id,
                        doc_id,
                        content,
                        _estimate_tokens(content),
                        now,
                        now,
                        doc["sha256"],
                    ),
                )
        conn.commit()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate documentation summaries and excerpts.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--runtime-dir", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()
    runtime_dir = Path(args.runtime_dir).resolve()
    run_pipeline(project_root, runtime_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
