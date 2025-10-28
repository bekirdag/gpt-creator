#!/usr/bin/env python3
"""Estimate remaining work based on story points and throughput metadata."""

from __future__ import annotations

import math
import re
import sqlite3
import sys
from pathlib import Path
from typing import Tuple


DEFAULT_RATE = 15.0


def parse_points(raw: object) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return max(float(raw), 0.0)
    text = str(raw).strip()
    if not text:
        return 0.0
    normalized = text.lower().replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return 0.0
    try:
        return max(float(match.group(0)), 0.0)
    except ValueError:
        return 0.0


def fetch_rate(cursor: sqlite3.Cursor) -> Tuple[float, int]:
    rate_value = None
    samples = 0
    try:
        row = cursor.execute(
            "SELECT value FROM metadata WHERE key = ?", ("throughput.rate_sp_per_hour",)
        ).fetchone()
        if row and row["value"] not in (None, ""):
            rate_value = float(row["value"])
    except Exception:
        rate_value = None

    try:
        row = cursor.execute(
            "SELECT value FROM metadata WHERE key = ?", ("throughput.samples",)
        ).fetchone()
        if row and row["value"] not in (None, ""):
            samples = int(float(row["value"]))
    except Exception:
        samples = 0

    if rate_value is not None and rate_value > 0 and samples > 0:
        return rate_value, samples
    return DEFAULT_RATE, 0


def table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    try:
        row = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        return False


def fmt_float(value: float) -> str:
    if math.isclose(value, round(value), rel_tol=1e-9, abs_tol=1e-9):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_tokens(value: float) -> str:
    return f"{int(round(value)):,}"


def estimate(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rate, rate_samples = fetch_rate(cur)
    try:
        rows = cur.execute("SELECT id, story_points, status FROM tasks").fetchall()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise SystemExit(f"Failed to read tasks: {exc}")

    done_statuses = {"complete", "completed", "done"}
    total_points = 0.0
    remaining_tasks = 0
    completed_points = 0.0
    task_info: dict[str, dict[str, float | str]] = {}

    for row in rows:
        status = (row["status"] or "").strip().lower()
        points = parse_points(row["story_points"])
        task_info[row["id"]] = {"points": points, "status": status}
        if status in done_statuses:
            completed_points += points
            continue
        remaining_tasks += 1
        total_points += points

    tokens_total = 0.0
    token_samples = 0
    covered_points = 0.0

    if table_exists(cur, "task_progress"):
        token_by_task: dict[str, float] = {}
        try:
            for progress in cur.execute(
                "SELECT id, task_id, tokens_total FROM task_progress "
                "WHERE tokens_total IS NOT NULL AND tokens_total > 0 "
                "ORDER BY id"
            ):
                task_id = progress["task_id"]
                if task_id is None:
                    continue
                token_by_task[task_id] = float(progress["tokens_total"])
        except sqlite3.DatabaseError:
            token_by_task = {}

        token_samples = len(token_by_task)
        for task_id, tokens in token_by_task.items():
            tokens_total += tokens
            info = task_info.get(task_id)
            if info:
                covered_points += float(info["points"])

    conn.close()

    if remaining_tasks == 0:
        print("All tasks are complete. No remaining story points.")
        return 0

    if rate <= 0:
        rate = DEFAULT_RATE

    total_minutes = math.ceil((total_points / rate) * 60) if total_points > 0 else 0
    days, rem_minutes = divmod(total_minutes, 1440)
    hours, minutes = divmod(rem_minutes, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    estimate_str = " ".join(parts)

    print(f"Remaining tasks: {remaining_tasks}")
    print(f"Remaining story points: {fmt_float(total_points)}")
    if rate_samples > 0 and rate > 0:
        sample_label = "sample" if rate_samples == 1 else "samples"
        print(f"Measured throughput: {fmt_float(rate)} SP/hour (based on {rate_samples} {sample_label}).")
    else:
        print("Using default throughput assumption: 15 SP/hour.")
    print(f"Estimated completion time @{fmt_float(rate)} SP/hour: {estimate_str}")

    if tokens_total > 0 and token_samples > 0:
        print(f"Tokens observed: {fmt_tokens(tokens_total)} across {token_samples} task(s).")
        if covered_points > 0:
            avg_tokens_per_point = tokens_total / covered_points
            print(
                f"Average tokens per story point: {fmt_float(avg_tokens_per_point)} tokens/SP "
                f"(based on {fmt_float(covered_points)} SP)."
            )
            estimated_tokens_hour = avg_tokens_per_point * rate if rate > 0 else 0.0
            if estimated_tokens_hour > 0:
                print(
                    f"Estimated token burn @{fmt_float(rate)} SP/hour: "
                    f"{fmt_tokens(estimated_tokens_hour)} tokens/hour."
                )
            projected_remaining = avg_tokens_per_point * total_points if total_points > 0 else 0.0
            if projected_remaining > 0:
                print(
                    f"Projected remaining tokens: {fmt_tokens(projected_remaining)} tokens for "
                    f"{fmt_float(total_points)} SP."
                )
        else:
            print("Average tokens per story point: insufficient data (no story points recorded on tokenized tasks).")
    else:
        print("Token usage data unavailable; run work-on-tasks to capture token telemetry.")

    return 0


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(1)
    db_path = Path(sys.argv[1])
    if not db_path.exists():
        raise SystemExit(f"Tasks database not found: {db_path}")
    raise SystemExit(estimate(db_path))


if __name__ == "__main__":
    main()
