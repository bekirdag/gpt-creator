#!/usr/bin/env python3
"""Summarise refinement progress for tasks backlog."""

import sqlite3
import sys


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit("Usage: refine_tasks_summary.py TASKS_DB_PATH [STORY_FILTER]")

    db_path = argv[1]
    filters_raw = argv[2] if len(argv) > 2 else ""
    filters = {value.strip().lower() for value in filters_raw.split(",") if value.strip()}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(tasks)")
    cols = {row[1] for row in cur.fetchall()}
    have_refined = "refined" in cols

    story_map = {
        (row[0] or "").strip(): (row[1] or "").strip().lower()
        for row in cur.execute("SELECT story_slug, story_id FROM stories")
    }

    def story_in_scope(slug: str) -> bool:
        lower = slug.lower()
        if not filters:
            return True
        if lower in filters:
            return True
        story_id_lower = story_map.get(slug, "")
        if story_id_lower in filters:
            return True
        return False

    if have_refined:
        rows = cur.execute(
            "SELECT story_slug, COALESCE(refined, 0) FROM tasks"
        ).fetchall()
    else:
        rows = [(slug, 0) for (slug,) in cur.execute("SELECT story_slug FROM tasks").fetchall()]

    conn.close()

    total_tasks = 0
    refined_tasks = 0
    stories_total = set()
    stories_pending = set()

    for slug, refined in rows:
        slug = (slug or "").strip()
        if not slug or not story_in_scope(slug):
            continue
        stories_total.add(slug)
        total_tasks += 1
        try:
            refined_value = int(refined)
        except Exception:
            refined_value = 0
        if refined_value:
            refined_tasks += 1
        else:
            stories_pending.add(slug)

    pending_tasks = total_tasks - refined_tasks
    print(
        total_tasks,
        refined_tasks,
        pending_tasks,
        len(stories_total),
        len(stories_pending),
    )


if __name__ == "__main__":
    main(sys.argv)
