#!/usr/bin/env python3
"""Return the next backlog story with remaining work."""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Optional


TERMINAL_PREFIXES = ("complete", "completed", "done", "skipped", "skip")


def normalize_status(value: Optional[str]) -> str:
    text = (value or "").strip().lower().replace("_", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def status_is_terminal(value: Optional[str]) -> bool:
    status = normalize_status(value)
    if not status:
        return False
    tokens = {status}
    tokens.update(filter(None, re.split(r"[^a-z0-9]+", status)))
    for token in tokens:
        for prefix in TERMINAL_PREFIXES:
            if token.startswith(prefix):
                return True
    return False


def slug_key(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def load_story_rows(cur: sqlite3.Cursor) -> list[sqlite3.Row]:
    cur.execute(
        """
        SELECT story_slug, story_id, status, completed_tasks, total_tasks, sequence
        FROM stories
        ORDER BY COALESCE(sequence, 0) ASC, story_slug COLLATE NOCASE ASC
        """
    )
    return cur.fetchall()


def to_int(value: object) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, bool):
        return int(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_task_counts(cur: sqlite3.Cursor, slug_lookup: Dict[str, str]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    for row in cur.execute("SELECT story_slug, story_id, status FROM tasks"):
        raw_slug = row["story_slug"]
        raw_story_id = row["story_id"]
        slug = slug_lookup.get(slug_key(raw_slug), "")
        if not slug and raw_story_id:
            slug = slug_lookup.get(slug_key(raw_story_id), "")
        if not slug:
            continue
        bucket = counts.setdefault(slug, {"total": 0, "completed": 0, "pending": 0})
        bucket["total"] += 1
        if status_is_terminal(row["status"]):
            bucket["completed"] += 1
        else:
            bucket["pending"] += 1
    return counts


def story_has_pending(row: sqlite3.Row, counts: Dict[str, Dict[str, int]]) -> bool:
    slug = row["story_slug"] or ""
    info = counts.get(slug)
    total_field = to_int(row["total_tasks"])
    completed_field = to_int(row["completed_tasks"])

    if info:
        if info["pending"] > 0:
            return True
        if info["total"] > 0 and info["completed"] < info["total"]:
            return True

    total = total_field
    completed = completed_field

    if total is not None and completed is not None:
        if completed < total:
            return True
    elif info:
        # Already handled via counts above
        pass
    else:
        # Without reliable counts, treat non-terminal stories as pending
        if not status_is_terminal(row["status"]):
            return True

    return False


def pick_next_story(
    rows: list[sqlite3.Row], counts: Dict[str, Dict[str, int]], after_slug: Optional[str]
) -> Optional[str]:
    if not rows:
        return None

    after_key = slug_key(after_slug)
    after_sequence: Optional[int] = None

    if after_key:
        for row in rows:
            slug = row["story_slug"] or ""
            if slug_key(slug) == after_key:
                if story_has_pending(row, counts):
                    return slug
                sequence = row["sequence"]
                after_sequence = int(sequence) if isinstance(sequence, int) else 0
                break

    if after_sequence is not None:
        for row in rows:
            if not story_has_pending(row, counts):
                continue
            slug = row["story_slug"] or ""
            sequence = row["sequence"]
            seq_value = int(sequence) if isinstance(sequence, int) else 0
            if seq_value > after_sequence:
                return slug

    for row in rows:
        if story_has_pending(row, counts):
            return row["story_slug"] or ""

    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: next_story_after.py <tasks_db> [<after_story_slug>]", file=sys.stderr)
        return 2

    db_path = Path(argv[1]).expanduser()
    after_slug = argv[2] if len(argv) > 2 and argv[2] else None

    if not db_path.exists():
        print("NONE")
        return 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        rows = load_story_rows(cur)
        slug_lookup: Dict[str, str] = {}
        for row in rows:
            slug = row["story_slug"] or ""
            if not slug:
                continue
            key = slug_key(slug)
            if key and key not in slug_lookup:
                slug_lookup[key] = slug
            story_id = row["story_id"] or ""
            if story_id:
                sid_key = slug_key(story_id)
                if sid_key and sid_key not in slug_lookup:
                    slug_lookup[sid_key] = slug

        counts = load_task_counts(cur, slug_lookup)
        next_story = pick_next_story(rows, counts, after_slug)
    finally:
        conn.close()

    print(next_story if next_story else "NONE")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
