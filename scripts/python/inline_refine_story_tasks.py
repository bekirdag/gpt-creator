#!/usr/bin/env python3
"""Determine which story tasks require inline refinement."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_TEXT_FIELDS = ("title", "description")
REQUIRED_LIST_FIELDS = (
    "acceptance_criteria",
    "tags",
    "assignees",
    "document_references",
    "endpoints",
    "data_contracts",
    "qa_notes",
)


def normalized_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def is_positive(value, zero_ok: bool = False) -> bool:
    try:
        if isinstance(value, str):
            value = float(value.strip())
        return value >= 0 if zero_ok else value > 0
    except Exception:
        return False


def needs_refine(task: dict) -> bool:
    for field in REQUIRED_TEXT_FIELDS:
        if not isinstance(task.get(field), str) or not task.get(field).strip():
            return True
    for field in REQUIRED_LIST_FIELDS:
        if not normalized_list(task.get(field)):
            return True
    if not is_positive(task.get("story_points"), zero_ok=False):
        return True
    if not is_positive(task.get("estimate"), zero_ok=False):
        return True
    return False


def main() -> int:
    if len(sys.argv) < 3:
        return 1

    path = Path(sys.argv[1])
    mode = sys.argv[2].strip().lower()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 1

    tasks = payload.get("tasks") or []
    mode_normalized = {"auto": "auto", "automatic": "auto", "all": "all"}.get(mode, mode)

    indices: list[int] = []
    for idx, task in enumerate(tasks):
        if mode_normalized == "all":
            indices.append(idx)
        elif mode_normalized == "auto":
            if needs_refine(task):
                indices.append(idx)
        else:
            indices = []
            break

    print(len(tasks))
    for idx in indices:
        print(idx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
