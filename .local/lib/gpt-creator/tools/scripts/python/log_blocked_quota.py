#!/usr/bin/env python3
"""Append a blocked-quota telemetry row based on a prompt meta file."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict


def _load_meta(path: Path) -> Dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _append_row(log_path: Path, row: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_blocked_quota(meta_path: Path, *, task_id: str, story_slug: str, run_id: str, model: str, log_path: Path) -> None:
    meta = _load_meta(meta_path)
    if not meta or str(meta.get("status", "")).strip().lower() != "blocked-quota":
        return

    timestamp = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    pruned_section = meta.get("pruned") or {}
    row: Dict[str, Any] = {
        "ts": timestamp,
        "run_id": run_id,
        "story_slug": story_slug,
        "task_id": task_id,
        "model": model,
        "blocked_quota": True,
        "token_budget_soft": meta.get("token_budget_soft"),
        "token_budget_hard": meta.get("token_budget_hard"),
        "token_used_est": meta.get("token_estimate_final"),
        "reserved_output": meta.get("reserved_output"),
        "pruned_items": pruned_section.get("items", {}),
        "pruned_bytes": pruned_section.get("bytes", 0),
    }
    _append_row(log_path, row)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Log a blocked-quota telemetry row.")
    parser.add_argument("--meta", required=True, type=Path, help="Path to the prompt meta JSON file.")
    parser.add_argument("--task-id", default="", help="Task identifier associated with the prompt.")
    parser.add_argument("--story-slug", default="", help="Story slug for the task.")
    parser.add_argument("--run-id", default="", help="Run identifier for the work-on-tasks loop.")
    parser.add_argument("--model", default="", help="Model name used for the prompt.")
    parser.add_argument("--log", required=True, type=Path, help="Destination NDJSON log file.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    log_blocked_quota(
        args.meta,
        task_id=args.task_id or "",
        story_slug=args.story_slug or "",
        run_id=args.run_id or "",
        model=args.model or "",
        log_path=args.log,
    )


if __name__ == "__main__":
    main()
