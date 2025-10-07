#!/usr/bin/env python3
"""Export a story and its tasks from tasks.db into the JSON format used for refinement."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List


def parse_json_field(payload: Any) -> List[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if item not in (None, "")]
    text = str(payload).strip()
    if not text:
        return []
    try:
        value = json.loads(text)
    except Exception:
        return [text]
    if isinstance(value, list):
        return [item for item in value if str(item).strip()]
    return [value]


def parse_text_list(payload: Any) -> List[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    text = str(payload).strip()
    if not text:
        return []
    # Attempt JSON decode first
    try:
        value = json.loads(text)
    except Exception:
        value = None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    # Fallback: split on common delimiters
    parts = [part.strip() for part in text.replace(";", ",").split(",")]
    return [part for part in parts if part]


def main() -> None:
    if len(sys.argv) not in (4, 5):
        raise SystemExit(
            "Usage: export_story_from_db.py <tasks.db> <story_slug> <output.json> [mode]"
        )

    db_path = Path(sys.argv[1])
    story_slug = sys.argv[2]
    output_path = Path(sys.argv[3])
    mode = sys.argv[4].strip().lower() if len(sys.argv) == 5 else "pending"
    if mode not in {"pending", "all"}:
        raise SystemExit("mode must be 'pending' or 'all'")

    if not db_path.exists():
        raise SystemExit(f"Tasks database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    story_row = cur.execute(
        "SELECT story_slug, story_id, story_title, epic_key, epic_title FROM stories WHERE story_slug = ?",
        (story_slug,),
    ).fetchone()
    if story_row is None:
        raise SystemExit(f"Story slug not found in database: {story_slug}")

    cur.execute("PRAGMA table_info(tasks)")
    table_info = cur.fetchall()
    have_refined = any(row[1] == "refined" for row in table_info)
    column_names = {row[1] for row in table_info}

    if mode == "pending" and not have_refined:
        mode = "all"

    if mode == "all":
        task_rows = cur.execute(
            "SELECT * FROM tasks WHERE story_slug = ? ORDER BY position ASC",
            (story_slug,),
        ).fetchall()
    else:
        task_rows = cur.execute(
            "SELECT * FROM tasks WHERE story_slug = ? AND COALESCE(refined, 0) = 0 ORDER BY position ASC",
            (story_slug,),
        ).fetchall()
    conn.close()

    story_id = (story_row["story_id"] or "").strip()
    story_title = (story_row["story_title"] or "").strip()
    epic_id = (story_row["epic_key"] or "").strip()
    epic_title = (story_row["epic_title"] or "").strip()

    tasks: List[Dict[str, Any]] = []
    pending_indices: List[int] = []
    for row in task_rows:
        row_dict = dict(row)
        task_id = (row_dict.get("task_id") or "").strip()
        if not task_id:
            position = row_dict.get("position") or 0
            task_id = f"{story_id or story_slug}-T{int(position) + 1:02d}"
        refined_flag = int((row_dict.get("refined") or 0)) if have_refined else 0
        if refined_flag == 0:
            pending_indices.append(len(tasks))
        tasks.append(
            {
                "id": task_id,
                "title": (row_dict.get("title") or "").strip(),
                "description": (row_dict.get("description") or "").strip(),
                "estimate": (row_dict.get("estimate") or "").strip(),
                "story_points": (row_dict.get("story_points") or "").strip(),
                "acceptance_criteria": parse_json_field(row_dict.get("acceptance_json")),
                "dependencies": parse_json_field(row_dict.get("dependencies_json")),
                "tags": parse_json_field(row_dict.get("tags_json")),
                "assignees": parse_json_field(row_dict.get("assignees_json")),
                "document_references": parse_text_list(row_dict.get("document_reference")),
                "endpoints": parse_text_list(row_dict.get("endpoints")) if "endpoints" in column_names else [],
                "qa_notes": parse_text_list(row_dict.get("qa_notes")) if "qa_notes" in column_names else [],
                "rbac": parse_text_list(row_dict.get("rbac")) if "rbac" in column_names else [],
                "observability": parse_text_list(row_dict.get("observability")) if "observability" in column_names else [],
                "performance_targets": parse_text_list(row_dict.get("performance_targets")) if "performance_targets" in column_names else [],
                "messaging_workflows": parse_text_list(row_dict.get("messaging_workflows")) if "messaging_workflows" in column_names else [],
                "idempotency": (row_dict.get("idempotency") or "").strip(),
                "rate_limits": (row_dict.get("rate_limits") or "").strip(),
                "user_story_ref_id": (row_dict.get("user_story_ref_id") or "").strip(),
                "epic_ref_id": (row_dict.get("epic_ref_id") or "").strip(),
                "refined": refined_flag,
                "refined_at": (row_dict.get("refined_at") or "").strip() if have_refined else "",
            }
        )

    payload = {
        "story_id": story_id,
        "story_title": story_title,
        "epic_id": epic_id,
        "epic_title": epic_title,
        "tasks": tasks,
        "pending_indices": pending_indices,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(len(pending_indices))


if __name__ == "__main__":
    main()
