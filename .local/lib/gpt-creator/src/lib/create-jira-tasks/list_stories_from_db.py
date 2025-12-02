#!/usr/bin/env python3
"""Print story slugs (and optionally filter) from tasks.db."""
from __future__ import annotations

import sqlite3
import sys


def main() -> None:
    if len(sys.argv) not in (2, 3, 4):
        raise SystemExit("Usage: list_stories_from_db.py <tasks.db> [filter] [mode]")

    db_path = sys.argv[1]
    filter_value = sys.argv[2] if len(sys.argv) >= 3 else ""
    mode = sys.argv[3].strip().lower() if len(sys.argv) == 4 else "pending"
    if mode not in {"pending", "all"}:
        raise SystemExit("mode must be 'pending' or 'all'")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(tasks)")
    have_refined = any(row[1] == "refined" for row in cur.fetchall())

    if mode == "pending" and not have_refined:
        mode = "all"

    if mode == "all":
        rows = cur.execute(
            "SELECT story_slug, story_id FROM stories ORDER BY sequence, story_slug"
        ).fetchall()
    else:
        rows = cur.execute(
            """
            SELECT s.story_slug, s.story_id
              FROM stories s
             WHERE EXISTS (
                     SELECT 1 FROM tasks t
                      WHERE t.story_slug = s.story_slug
                        AND COALESCE(t.refined, 0) = 0
                   )
             ORDER BY s.sequence, s.story_slug
            """
        ).fetchall()
    conn.close()

    filters = {value.strip() for value in filter_value.split(',') if value.strip()}
    filters_lower = {value.lower() for value in filters}
    for row in rows:
        slug = (row["story_slug"] or "").strip()
        story_id = (row["story_id"] or "").strip()
        if not slug:
            continue
        if filters_lower:
            slug_lower = slug.lower()
            story_id_lower = story_id.lower()
            if slug_lower not in filters_lower and story_id_lower not in filters_lower:
                continue
        print(slug)


if __name__ == "__main__":
    main()
