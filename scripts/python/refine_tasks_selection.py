#!/usr/bin/env python3
"""Select task indices for refinement based on current story JSON and mode."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable


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
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def is_positive(value, zero_ok: bool = False) -> bool:
    if isinstance(value, (int, float)):
        return value >= 0 if zero_ok else value > 0
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except Exception:
            return False
        return number >= 0 if zero_ok else number > 0
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


def coerce_indices(candidate: Iterable) -> list[int]:
    indices: list[int] = []
    for value in candidate:
        try:
            idx = int(value)
        except Exception:
            continue
        if idx >= 0:
            indices.append(idx)
    return indices


def main() -> int:
    if len(sys.argv) < 3:
        return 1

    path = Path(sys.argv[1])
    mode = (sys.argv[2] if len(sys.argv) > 2 else "auto").strip().lower()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 1

    tasks = payload.get("tasks") or []

    pending = payload.get("pending_indices")
    if isinstance(pending, list) and pending:
        indices = [idx for idx in coerce_indices(pending) if idx < len(tasks)]
    else:
        indices = list(range(len(tasks)))

    mode_map = {
        "auto": "auto",
        "automatic": "auto",
        "all": "all",
        "pending": "pending",
    }
    mode = mode_map.get(mode, mode)

    if mode in {"off", "disabled", "none", "skip", "0"}:
        print("SKIP")
        return 0

    if mode in {"all", "pending"}:
        selected = indices
    else:
        selected = []
        for idx in indices:
            task = tasks[idx] if idx < len(tasks) else {}
            if needs_refine(task):
                selected.append(idx)

    print(len(indices))
    for idx in selected:
        print(idx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
