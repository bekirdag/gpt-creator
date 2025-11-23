#!/usr/bin/env python3
"""Emit the pending task queue respecting the persisted global order."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import List, Tuple

TERMINAL_PREFIXES = ("completed-", "done-", "skipped-")
TERMINAL_STATUSES = {
    "complete",
    "completed",
    "completed-no-changes",
    "ready-to-review",
    "ready_for_review",
    "ready_for_qa",
    "ready-to-qa",
    "done",
    "skipped",
    "skipped-already-complete",
}


def _is_terminal(status: str) -> bool:
    value = (status or "").strip().lower().replace("_", "-")
    if not value:
        return False
    if value in TERMINAL_STATUSES:
        return True
    return any(value.startswith(prefix) for prefix in TERMINAL_PREFIXES)


def _task_filter_value(story_slug: str, task_id: str, position: int) -> str:
    if task_id and task_id.strip():
        return task_id.strip()
    return f"{story_slug.lower()}:{position + 1}"


def fetch_queue(db_path: Path) -> List[Tuple[int, str, str, int]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        rows = cur.execute(
            """
            SELECT global_order, story_slug, task_id, position, status
              FROM tasks
             WHERE global_order > 0
             ORDER BY global_order ASC
            """
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise SystemExit(f"Unable to select from tasks table ({exc}). Did you run update_global_task_order.py?") from exc
    finally:
        conn.close()

    queue: List[Tuple[int, str, str, int]] = []
    for row in rows:
        status = (row["status"] or "").strip()
        if _is_terminal(status):
            continue
        story_slug = (row["story_slug"] or "").strip()
        task_id = (row["task_id"] or "").strip()
        position = int(row["position"])
        queue.append(
            (
                int(row["global_order"]),
                story_slug,
                _task_filter_value(story_slug, task_id, position),
                position,
            )
        )
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the pending global task queue.")
    parser.add_argument("db_path", type=Path, help="Path to the tasks SQLite database.")
    args = parser.parse_args()

    queue = fetch_queue(args.db_path)
    for order, story_slug, task_filter, position in queue:
        print(f"{order}\t{story_slug}\t{task_filter}\t{position}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
