#!/usr/bin/env python3
"""Populate task_dependencies table from task metadata."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Set


def ensure_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_dependencies (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          blocker_id TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_dependencies_unique
          ON task_dependencies (task_id, blocker_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_task
          ON task_dependencies (task_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_blocker
          ON task_dependencies (blocker_id)
        """
    )


def parse_dependencies(raw: str | None) -> Iterable[str]:
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except json.JSONDecodeError:
        pass
    # Fallback: treat as comma / newline separated text
    separators = ",\n"
    candidates: List[str] = []
    token = ""
    for char in raw:
        if char in separators:
            token = token.strip()
            if token:
                candidates.append(token)
            token = ""
        else:
            token += char
    token = token.strip()
    if token:
        candidates.append(token)
    return candidates


def populate_dependencies(
    db_path: Path,
    *,
    only_if_empty: bool,
    force: bool,
    purge_unknown: bool = True,
) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ensure_table(cur)

    existing_count = 0
    try:
        existing_count = cur.execute("SELECT COUNT(*) FROM task_dependencies").fetchone()[0]
    except sqlite3.DatabaseError:
        existing_count = 0

    if only_if_empty and existing_count > 0 and not force:
        print(f"[order] task_dependencies already populated ({existing_count} rows); refreshing missing entries.")
    if force:
        cur.execute("DELETE FROM task_dependencies")
        existing_count = 0
        print("[order] Cleared existing task_dependencies (force).")

    rows = cur.execute(
        """
        SELECT task_id, dependencies_json, dependencies_text
          FROM tasks
         WHERE task_id IS NOT NULL AND TRIM(task_id) <> ''
        """
    ).fetchall()

    inserted = 0
    for row in rows:
        raw_task_id = (row["task_id"] or "").strip()
        if not raw_task_id:
            continue
        task_id = raw_task_id
        task_key = task_id.lower()

        cur.execute("DELETE FROM task_dependencies WHERE LOWER(task_id) = ?", (task_key,))

        seen: dict[str, str] = {}
        for dep in parse_dependencies(row["dependencies_json"]):
            dep_norm = dep.strip()
            if dep_norm and dep_norm.lower() != task_id.lower():
                dep_key = dep_norm.lower()
                seen.setdefault(dep_key, dep_norm)
        for dep in parse_dependencies(row["dependencies_text"]):
            dep_norm = dep.strip()
            if dep_norm and dep_norm.lower() != task_id.lower():
                dep_key = dep_norm.lower()
                seen.setdefault(dep_key, dep_norm)
        for dep_key, blocker in seen.items():
            cur.execute(
                "INSERT OR IGNORE INTO task_dependencies (task_id, blocker_id) VALUES (?, ?)",
                (task_id, blocker),
            )
            if cur.rowcount:
                inserted += 1

    if purge_unknown:
        cur.execute(
            """
            DELETE FROM task_dependencies
                  WHERE LOWER(task_id) NOT IN (
                        SELECT LOWER(TRIM(task_id)) FROM tasks WHERE TRIM(task_id) <> ''
                  )
                     OR LOWER(blocker_id) NOT IN (
                        SELECT LOWER(TRIM(task_id)) FROM tasks WHERE TRIM(task_id) <> ''
                  )
            """
        )

    conn.commit()
    conn.close()
    print(f"[order] Populated {inserted} dependency row(s).")
    return inserted


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Populate task_dependencies from task metadata.")
    parser.add_argument("db_path", type=Path, help="Path to tasks SQLite database.")
    parser.add_argument(
        "--only-if-empty",
        action="store_true",
        help="Skip population when task_dependencies already contains rows.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear existing task_dependencies rows before repopulating.",
    )
    args = parser.parse_args(argv)

    if not args.db_path.exists():
        print(f"[order] tasks database not found at {args.db_path}", file=sys.stderr)
        return 1

    populate_dependencies(args.db_path, only_if_empty=args.only_if_empty, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
