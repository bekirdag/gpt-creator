#!/usr/bin/env python3
"""Compute average token usage per story point for task estimates."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import estimate_remaining_work as erw


def build_task_info(cur: sqlite3.Cursor) -> Dict[str, Dict[str, Any]]:
    """Replicate the task status resolution logic from estimate_remaining_work."""
    if not erw.table_exists(cur, "tasks"):
        return {}
    task_columns = {str(info[1] or "").strip().lower() for info in cur.execute("PRAGMA table_info(tasks)")}
    select_fields = ["id", "story_slug", "position", "story_points", "status", "task_id"]
    include_progress_state = "progress_state" in task_columns
    include_last_apply_status = "last_apply_status" in task_columns
    include_last_verify_status = "last_verify_status" in task_columns
    include_last_story_points = "last_story_points" in task_columns
    if include_progress_state:
        select_fields.append("progress_state")
    if include_last_apply_status:
        select_fields.append("last_apply_status")
    if include_last_verify_status:
        select_fields.append("last_verify_status")
    if include_last_story_points:
        select_fields.append("last_story_points")

    try:
        rows = cur.execute(f"SELECT {', '.join(select_fields)} FROM tasks").fetchall()
    except sqlite3.DatabaseError:
        return {}

    progress_overrides = erw.fetch_progress_status_map(cur)
    progress_story_points = erw.fetch_progress_story_points_map(cur)
    task_info: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        base_status = row["status"] or ""
        points = erw.parse_points(row["story_points"])
        if points <= 0 and include_last_story_points and "last_story_points" in row.keys():
            fallback_last = erw.parse_points(row["last_story_points"])
            if fallback_last > 0:
                points = fallback_last
        (
            effective_status,
            candidate_statuses,
            candidate_keys,
            _,
            _,
        ) = erw.determine_effective_status(
            base_status,
            row,
            progress_overrides,
            include_progress_state,
            include_last_apply_status=include_last_apply_status,
            include_last_verify_status=include_last_verify_status,
        )
        if points <= 0 and progress_story_points:
            for key in candidate_keys:
                candidate_points = progress_story_points.get(key)
                if candidate_points and candidate_points > 0:
                    points = candidate_points
                    break
        status_options: list[str] = []
        for candidate in [effective_status, *candidate_statuses, erw.coerce_status(base_status)]:
            candidate_norm = erw.coerce_status(candidate or "", "")
            if not candidate_norm:
                continue
            if candidate_norm not in status_options:
                status_options.append(candidate_norm)
        if not status_options:
            status_options.append("pending")
        resolved_status = ""
        for candidate in status_options:
            if erw.is_done_status(candidate):
                resolved_status = candidate
                break
        if not resolved_status:
            resolved_status = status_options[0]
        task_key_primary = str(row["id"])
        task_info[task_key_primary] = {"points": points, "status": resolved_status}
        story_slug = (row["story_slug"] or "").strip()
        position = row["position"]
        if story_slug and position is not None:
            task_info[f"{story_slug}:{position}"] = {"points": points, "status": resolved_status}
        task_id_value = (row["task_id"] or "").strip()
        if task_id_value:
            task_info[task_id_value] = {"points": points, "status": resolved_status}

    return task_info


def compute_avg_tokens_per_point(
    db_path: Path,
    recent_task_limit: Optional[int],
    scope: str,
) -> Tuple[float, float, float, int, int, int]:
    project_root = erw.infer_project_root(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    task_info = build_task_info(cur)
    recent_samples, total_recent_samples = erw.fetch_recent_productive_samples(
        cur, recent_task_limit, scope=scope, project_root=project_root
    )

    tokens_total = 0.0
    covered_points = 0.0
    token_samples = 0

    if recent_samples:
        for sample in recent_samples:
            sp_value = max(float(sample["sp_delivered"] or 0.0), 0.0)
            tokens_value = float(sample["tokens_total"] or 0.0)
            if tokens_value > 0:
                tokens_total += tokens_value
                covered_points += sp_value
                token_samples += 1
    else:
        token_by_task: Dict[str, float] = {}
        if erw.table_exists(cur, "doc_observations"):
            try:
                for observation in cur.execute(
                    "SELECT task_id, SUM(tokens) AS total_tokens FROM doc_observations GROUP BY task_id"
                ):
                    task_key = observation["task_id"]
                    tokens_value = observation["total_tokens"] or 0
                    if task_key:
                        token_by_task[str(task_key)] = float(tokens_value)
            except sqlite3.DatabaseError:
                token_by_task = {}
        elif erw.table_exists(cur, "task_progress"):
            try:
                for progress in cur.execute(
                    "SELECT task_id, tokens_total FROM task_progress "
                    "WHERE tokens_total IS NOT NULL AND tokens_total > 0 ORDER BY id"
                ):
                    task_id = progress["task_id"]
                    if task_id is None:
                        continue
                    token_by_task[str(task_id)] = float(progress["tokens_total"])
            except sqlite3.DatabaseError:
                token_by_task = {}

        token_samples = len(token_by_task)
        for task_key, tokens in token_by_task.items():
            tokens_total += tokens
            info = task_info.get(task_key)
            if info and erw.is_done_status(str(info.get("status", ""))):
                try:
                    covered_points += float(info.get("points", 0.0))
                except (TypeError, ValueError):
                    continue

    conn.close()

    avg_tokens = (tokens_total / covered_points) if covered_points > 0 else 0.0
    return (
        avg_tokens,
        tokens_total,
        covered_points,
        token_samples,
        len(recent_samples),
        len(total_recent_samples),
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Emit average tokens per story point for estimates.")
    parser.add_argument("db_path", help="Path to the tasks SQLite database.")
    parser.add_argument(
        "--recent-tasks",
        dest="recent_tasks",
        default=str(erw.RECENT_SAMPLE_LIMIT),
        help="Number of recent tasks to sample (default matches estimate command).",
    )
    parser.add_argument(
        "--scope",
        choices=("project", "all"),
        default="project",
        help="Restrict metric samples to the current project (default) or use all recorded samples.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON payload instead of the compact pipe-delimited format.",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"Tasks database not found: {db_path}")
    recent_limit = erw.parse_recent_tasks_arg(str(args.recent_tasks))
    avg_tokens, tokens_total, covered_points, token_samples, recent_count, window_total = (
        compute_avg_tokens_per_point(db_path, recent_limit, args.scope)
    )

    if args.json:
        import json

        payload = {
            "avg_tokens_per_sp": avg_tokens,
            "tokens_total": tokens_total,
            "covered_points": covered_points,
            "token_samples": token_samples,
            "recent_sample_count": recent_count,
            "recent_window_total": window_total,
        }
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
        return 0

    sys.stdout.write(
        f"{avg_tokens:.8f}|{token_samples}|{covered_points:.2f}|{tokens_total:.2f}|{recent_count}|{window_total}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
