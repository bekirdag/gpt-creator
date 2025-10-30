#!/usr/bin/env python3
"""Emit story queue entries for work-on-tasks."""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path


def norm(value: str | None) -> str:
    return (value or "").strip().lower()


def normalize(value: str | None) -> str:
    return (value or "").strip()


def slug_norm(value: str | None) -> str:
    slug = norm(value)
    if not slug:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", slug).strip("-")


def sanitize_field(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ")


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("Usage: work_select_stories.py DB_PATH STORY_FILTER RESUME_FLAG")

    db_path = Path(sys.argv[1])
    story_filter = norm(sys.argv[2])
    resume_flag = sys.argv[3] == "1"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    stories = cur.execute(
        "SELECT story_slug, story_id, story_title, epic_key, epic_title, sequence, status "
        "FROM stories ORDER BY sequence ASC, story_slug ASC"
    ).fetchall()

    start_allowed = not story_filter

    for story in stories:
        slug = normalize(story["story_slug"])
        sequence = story["sequence"] or 0
        story_id = normalize(story["story_id"])
        epic_key = normalize(story["epic_key"])
        epic_title = normalize(story["epic_title"])
        story_title = normalize(story["story_title"])

        story_title_clean = sanitize_field(story_title)
        epic_title_clean = sanitize_field(epic_title)
        epic_key_clean = sanitize_field(epic_key)
        story_id_clean = sanitize_field(story_id)

        if story_filter and not start_allowed:
            keys = {norm(story_id), norm(slug), norm(epic_key), norm(str(sequence))}
            if story_filter in keys:
                start_allowed = True
            else:
                continue

        task_rows = []
        slug_lower = norm(slug)
        if slug_lower:
            task_rows = cur.execute(
                'SELECT position, status FROM tasks WHERE LOWER(COALESCE(story_slug, "")) = ? ORDER BY position ASC',
                (slug_lower,),
            ).fetchall()

        if not task_rows and story_id:
            story_id_lower = norm(story_id)
            if story_id_lower:
                rows = cur.execute(
                    'SELECT id, position, status, story_slug FROM tasks WHERE LOWER(COALESCE(story_id, "")) = ? ORDER BY position ASC',
                    (story_id_lower,),
                ).fetchall()
                if rows:
                    task_rows = [(row["position"], row["status"]) for row in rows]
                    if slug_lower:
                        cur.execute(
                            'UPDATE tasks SET story_slug = ? WHERE LOWER(COALESCE(story_id, "")) = ?',
                            (slug, story_id_lower),
                        )
                        conn.commit()

        if not task_rows and slug_lower:
            slug_key = slug_norm(slug)
            if slug_key:
                task_rows = cur.execute(
                    'SELECT position, status FROM tasks WHERE LOWER(COALESCE(story_slug, "")) = ? ORDER BY position ASC',
                    (slug_key,),
                ).fetchall()

        total = len(task_rows)
        completed = 0
        next_index = 0
        for row in task_rows:
            status = (row[1] or "").strip().lower()
            if status == "complete":
                completed += 1
                continue
            next_index = row[0] or 0
            break
        else:
            next_index = total

        current_status = (story["status"] or "").strip()

        if resume_flag and not story_filter and current_status.lower() == "complete":
            continue

        if resume_flag:
            if total == 0:
                next_index = 0
            elif completed >= total:
                if story_filter:
                    next_index = total
                else:
                    continue
        else:
            next_index = 0 if total > 0 else 0

        print(
            "\t".join(
                [
                    str(sequence),
                    slug,
                    story_id_clean,
                    story_title_clean,
                    epic_key_clean,
                    epic_title_clean,
                    str(total),
                    str(next_index),
                    str(completed),
                    current_status,
                ]
            )
        )

    conn.close()


if __name__ == "__main__":
    main()
