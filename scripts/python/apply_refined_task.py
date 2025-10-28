#!/usr/bin/env python3
"""Apply refined task updates to a working story JSON."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path


def should_mark_refined() -> bool:
    return os.environ.get("CJT_DRY_RUN", "0") != "1"


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> int:
    if len(sys.argv) < 4:
        return 1

    working_path = Path(sys.argv[1])
    refined_path = Path(sys.argv[2])
    try:
        task_index = int(sys.argv[3])
    except Exception:
        return 1

    if not refined_path.exists():
        return 0

    refined_payload = load_json(refined_path)
    if not isinstance(refined_payload, dict):
        return 0

    task_data = refined_payload.get("task", refined_payload)
    if not isinstance(task_data, dict):
        return 0

    if not any(
        key in task_data for key in ("title", "description", "acceptance_criteria", "tags")
    ):
        return 0

    story_payload = load_json(working_path)
    if not isinstance(story_payload, dict):
        return 0

    tasks = story_payload.get("tasks")
    if not isinstance(tasks, list) or task_index < 0 or task_index >= len(tasks):
        return 0

    existing = tasks[task_index]
    if not isinstance(existing, dict):
        return 0

    for key, value in task_data.items():
        if value is None:
            continue
        existing[key] = value

    if should_mark_refined():
        existing["refined"] = 1
        existing["refined_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    story_payload["tasks"][task_index] = existing
    working_path.write_text(json.dumps(story_payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
