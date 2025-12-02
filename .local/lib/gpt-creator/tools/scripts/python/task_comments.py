#!/usr/bin/env python3
"""Task comment schema + helpers."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
import sys
from typing import Iterable, List, Optional, Sequence

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_comments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_row_id INTEGER,
  task_uid TEXT,
  story_slug TEXT NOT NULL,
  task_ref TEXT NOT NULL,
  commenter TEXT NOT NULL,
  details TEXT NOT NULL,
  status_from TEXT,
  status_to TEXT,
  severity TEXT,
  component TEXT,
  suggested_fix TEXT,
  blocking INTEGER NOT NULL DEFAULT 0,
  artifact_path TEXT,
  agent_run_id TEXT,
  created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(task_row_id) REFERENCES tasks(id) ON DELETE SET NULL
)
"""

CREATE_INDEX_STATEMENTS: Sequence[str] = (
    "CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments(task_row_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_task_comments_story_ref ON task_comments(story_slug, task_ref, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_task_comments_commenter ON task_comments(commenter, created_at DESC)",
)


def ensure_task_comments_schema(cur: sqlite3.Cursor) -> None:
    """Create task_comments table + indexes when missing."""
    cur.execute(CREATE_TABLE_SQL)
    cur.execute("PRAGMA table_info(task_comments)")
    existing_cols = {row[1] for row in cur.fetchall()}
    optional_cols = {
        "component": "TEXT",
        "suggested_fix": "TEXT",
        "blocking": "INTEGER NOT NULL DEFAULT 0",
    }
    for col, definition in optional_cols.items():
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE task_comments ADD COLUMN {col} {definition}")
    for statement in CREATE_INDEX_STATEMENTS:
        cur.execute(statement)


def insert_task_comment(
    cur: sqlite3.Cursor,
    *,
    task_row_id: Optional[int],
    task_uid: Optional[str],
    story_slug: str,
    task_ref: str,
    commenter: str,
    details: str,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
    severity: Optional[str] = None,
    component: Optional[str] = None,
    suggested_fix: Optional[str] = None,
    blocking: bool = False,
    artifact_path: Optional[str] = None,
    agent_run_id: Optional[str] = None,
) -> int:
    """
    Insert a comment for a task; returns the new comment id.

    - task_row_id is the numeric tasks.id when known (nullable for robustness).
    - task_uid/task_ref let us follow tasks across migrations or rewrites.
    """
    ensure_task_comments_schema(cur)
    blocking_int = 1 if blocking else 0
    cur.execute(
        """
        INSERT INTO task_comments (
          task_row_id, task_uid, story_slug, task_ref, commenter, details,
          status_from, status_to, severity, component, suggested_fix, blocking, artifact_path, agent_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_row_id,
            (task_uid or "").strip() or None,
            (story_slug or "").strip(),
            (task_ref or "").strip(),
            (commenter or "").strip(),
            (details or "").strip(),
            (status_from or "").strip() or None,
            (status_to or "").strip() or None,
            (severity or "").strip() or None,
            (component or "").strip() or None,
            (suggested_fix or "").strip() or None,
            blocking_int,
            (artifact_path or "").strip() or None,
            (agent_run_id or "").strip() or None,
        ),
    )
    return int(cur.lastrowid)


def fetch_task_comments(
    cur: sqlite3.Cursor,
    *,
    task_row_id: Optional[int] = None,
    story_slug: Optional[str] = None,
    task_ref: Optional[str] = None,
    limit: int = 100,
) -> List[sqlite3.Row]:
    """Return comments for a task ordered newest-first."""
    ensure_task_comments_schema(cur)
    clauses = []
    params: list = []
    if task_row_id is not None:
        clauses.append("task_row_id = ?")
        params.append(task_row_id)
    if story_slug:
        clauses.append("story_slug = ?")
        params.append(story_slug.strip())
    if task_ref:
        clauses.append("task_ref = ?")
        params.append(task_ref.strip())
    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)
    cur.execute(f"PRAGMA table_info(task_comments)")
    rows = cur.execute(
        f"""
        SELECT id, task_row_id, task_uid, story_slug, task_ref, commenter, details,
               status_from, status_to, severity, component, suggested_fix, blocking, artifact_path, agent_run_id,
               created_at, updated_at
          FROM task_comments
          {where}
         ORDER BY created_at DESC
         LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return list(rows)


def _main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description="Ensure task_comments schema exists.")
    parser.add_argument("db_path", type=Path, help="Path to tasks.db")
    args = parser.parse_args(list(argv))

    if not args.db_path.exists():
        print(f"Database not found: {args.db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(args.db_path))
    conn.row_factory = sqlite3.Row
    try:
        ensure_task_comments_schema(conn.cursor())
        conn.commit()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
