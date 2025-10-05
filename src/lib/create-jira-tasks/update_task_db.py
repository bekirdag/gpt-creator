#!/usr/bin/env python3
"""Update a single task row in tasks.db from a refined story JSON."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable, Any, List


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
        return [text]
    return [str(value).strip()]


def _join(values: Iterable[str]) -> str:
    cleaned = [item.strip() for item in values if item and item.strip()]
    return ", ".join(cleaned)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return _join(value)
    return str(value).strip()


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit(
            "Usage: update_task_db.py <tasks.db> <story.json> <story_slug> <task_index>"
        )

    db_path = Path(sys.argv[1])
    story_path = Path(sys.argv[2])
    story_slug = sys.argv[3]
    task_index = int(sys.argv[4])

    if not db_path.exists():
        raise SystemExit(f"Tasks database not found: {db_path}")
    if not story_path.exists():
        raise SystemExit(f"Story JSON not found: {story_path}")

    story_payload = json.loads(story_path.read_text(encoding="utf-8"))
    tasks = story_payload.get("tasks") or []
    if task_index < 0 or task_index >= len(tasks):
        raise SystemExit(0)

    task = tasks[task_index]

    story_id = _text(story_payload.get("story_id"))
    story_title = _text(story_payload.get("story_title"))
    epic_key = _text(story_payload.get("epic_id")).upper()
    epic_title = _text(story_payload.get("epic_title"))
    total_tasks = len(tasks)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    assignees = _as_list(task.get("assignees")) or _as_list(task.get("assignee"))
    tags = _as_list(task.get("tags"))
    acceptance = _as_list(task.get("acceptance_criteria"))
    dependencies = _as_list(task.get("dependencies"))

    task_id_value = _text(task.get("id") or task.get("task_id"))
    if task_id_value:
        task_id_value = task_id_value.upper()

    payload = {
        "task_id": task_id_value or None,
        "title": _text(task.get("title")) or None,
        "description": _text(task.get("description")) or None,
        "estimate": _text(task.get("estimate")) or None,
        "assignees_json": json.dumps(assignees, ensure_ascii=False),
        "tags_json": json.dumps(tags, ensure_ascii=False),
        "acceptance_json": json.dumps(acceptance, ensure_ascii=False),
        "dependencies_json": json.dumps(dependencies, ensure_ascii=False),
        "tags_text": _join(tags) or None,
        "story_points": _text(task.get("story_points")) or None,
        "dependencies_text": _join(dependencies) or None,
        "assignee_text": _join(assignees) or None,
        "document_reference": _text(task.get("document_reference") or task.get("document_references")) or None,
        "idempotency": _text(task.get("idempotency")) or None,
        "rate_limits": _text(task.get("rate_limits")) or None,
        "rbac": _text(task.get("rbac") or task.get("policy")) or None,
        "messaging_workflows": _text(task.get("messaging_workflows")) or None,
        "performance_targets": _text(task.get("performance_targets")) or None,
        "observability": _text(task.get("observability")) or None,
        "acceptance_text": _text(task.get("acceptance_text")) or None,
        "endpoints": _text(task.get("endpoints")) or None,
        "sample_create_request": _text(task.get("sample_create_request") or task.get("sample_request")) or None,
        "sample_create_response": _text(task.get("sample_create_response") or task.get("sample_response")) or None,
        "user_story_ref_id": _text(task.get("user_story_ref_id")) or None,
        "epic_ref_id": _text(task.get("epic_ref_id")) or None,
        "story_id": _text(task.get("story_id") or story_id) or None,
        "story_title": _text(task.get("story_title") or story_title) or None,
        "epic_key": epic_key or None,
        "epic_title": _text(task.get("epic_title") or epic_title) or None,
        "updated_at": now,
    }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('PRAGMA foreign_keys = ON')

    columns = ", ".join(f"{col} = ?" for col in payload)
    values = list(payload.values()) + [story_slug, task_index]

    cur.execute(
        f"UPDATE tasks SET {columns} WHERE story_slug = ? AND position = ?",
        values,
    )
    if cur.rowcount == 0:
        raise SystemExit(f"No task row found for story {story_slug} position {task_index}")

    # Update story metadata (total tasks, timestamps, ids)
    cur.execute(
        """
        UPDATE stories
           SET story_id = ?,
               story_title = ?,
               epic_key = ?,
               epic_title = ?,
               total_tasks = ?,
               updated_at = ?
         WHERE story_slug = ?
        """,
        (
            story_id or None,
            story_title or None,
            epic_key or None,
            epic_title or None,
            total_tasks,
            now,
            story_slug,
        ),
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
