#!/usr/bin/env python3
"""Estimate remaining work based on story points and throughput metadata."""

from __future__ import annotations

import math
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


DEFAULT_RATE = 15.0
NON_REMAINING_STATUSES = {
    "complete",
    "completed",
    "done",
    "completed-no-changes",
    "skipped-no-changes",
}
DEFAULT_CONTAMINATION_THRESHOLD = 0.2


def normalize_status(value: str) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = cleaned.replace("_", "-").replace(" ", "-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned


def meta_float(cursor: sqlite3.Cursor, key: str, default: float = 0.0) -> float:
    try:
        row = cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    except sqlite3.DatabaseError:
        return default
    if not row or row[0] in (None, ""):
        return default
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return default


def meta_text(cursor: sqlite3.Cursor, key: str) -> str:
    try:
        row = cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    except sqlite3.DatabaseError:
        return ""
    if not row or row[0] is None:
        return ""
    return str(row[0])


def meta_bool(cursor: sqlite3.Cursor, key: str) -> bool:
    value = meta_float(cursor, key, 0.0)
    return bool(int(value)) if value in {0.0, 1.0} else bool(value)


def infer_project_root(db_path: Path) -> Path:
    resolved = db_path.resolve()
    for parent in resolved.parents:
        if parent.name == ".gpt-creator":
            return parent.parent
    return resolved.parent


def load_eta_config(project_root: Path) -> Dict[str, float]:
    defaults = {
        "min_throughput_floor": 2.0,
        "stall_runs": 3.0,
        "blocked_threshold": 0.6,
    }
    config_path = project_root / ".gpt-creator" / "config.yml"
    if not config_path.exists() or yaml is None:
        return defaults
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(loaded, dict):
        return defaults
    eta_cfg = loaded.get("eta")
    if isinstance(eta_cfg, dict):
        floor_val = eta_cfg.get("min_throughput_floor")
        try:
            if floor_val is not None:
                defaults["min_throughput_floor"] = max(0.0, float(floor_val))
        except (TypeError, ValueError):
            pass
        stall_val = eta_cfg.get("stall_runs")
        try:
            if stall_val is not None:
                defaults["stall_runs"] = max(1.0, float(stall_val))
        except (TypeError, ValueError):
            pass
    return defaults


def compute_blocked_ratio(cur: sqlite3.Cursor, sample_limit: int) -> float:
    if sample_limit <= 0:
        return 0.0
    try:
        rows = cur.execute(
            "SELECT final_status FROM metric_samples ORDER BY occurred_at DESC LIMIT ?",
            (int(sample_limit),),
        ).fetchall()
    except sqlite3.DatabaseError:
        return 0.0
    if not rows:
        return 0.0
    blocked = 0
    total = 0
    for row in rows:
        status = normalize_status(row["final_status"] if "final_status" in row.keys() else str(row[0]))
        if not status:
            continue
        total += 1
        if status.startswith("blocked"):
            blocked += 1
    if total == 0:
        return 0.0
    return blocked / total


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


def fetch_rate(cursor: sqlite3.Cursor) -> Tuple[float, float, int, Dict[str, Any]]:
    rate_value = meta_float(cursor, "throughput.rate_sp_per_hour", DEFAULT_RATE)
    ewma_value = meta_float(cursor, "throughput.productive_ewma", rate_value)
    samples_value = meta_float(cursor, "throughput.samples", 0.0)

    extras = {
        "stalled": meta_bool(cursor, "throughput.stalled"),
        "stall_reason": meta_text(cursor, "throughput.stalled_reason"),
        "contamination_ratio": meta_float(cursor, "throughput.contamination_ratio", 0.0),
        "blocked_ratio": meta_float(cursor, "throughput.blocked_ratio", -1.0),
        "blocked_dominant": meta_text(cursor, "throughput.blocked_dominant"),
        "frozen": meta_bool(cursor, "throughput.frozen"),
        "contamination_threshold": meta_float(
            cursor, "metrics.contamination_threshold", DEFAULT_CONTAMINATION_THRESHOLD
        ),
    }

    rate = rate_value if rate_value > 0 else DEFAULT_RATE
    ewma = ewma_value if ewma_value > 0 else rate
    samples = int(max(0, round(samples_value)))
    return rate, ewma, samples, extras


def table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    try:
        row = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None
    except sqlite3.DatabaseError:
        return False


def count_remaining_tasks(cursor: sqlite3.Cursor) -> int:
    if not NON_REMAINING_STATUSES:
        row = cursor.execute("SELECT COUNT(*) FROM tasks").fetchone()
        return int(row[0]) if row else 0
    placeholders = ",".join("?" for _ in NON_REMAINING_STATUSES)
    query = (
        "SELECT COUNT(*) FROM tasks "
        f"WHERE LOWER(COALESCE(status, '')) NOT IN ({placeholders})"
    )
    row = cursor.execute(query, tuple(NON_REMAINING_STATUSES)).fetchone()
    return int(row[0]) if row else 0


def fmt_float(value: float) -> str:
    if math.isclose(value, round(value), rel_tol=1e-9, abs_tol=1e-9):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_tokens(value: float) -> str:
    return f"{int(round(value)):,}"


def estimate(db_path: Path) -> int:
    project_root = infer_project_root(db_path)
    eta_cfg = load_eta_config(project_root)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rate, ewma_rate, rate_samples, rate_meta = fetch_rate(cur)
    stalled_samples = int(max(1.0, eta_cfg.get("stall_runs", 3.0)))
    meta_blocked_ratio = rate_meta.get("blocked_ratio", -1.0)
    blocked_ratio = (
        meta_blocked_ratio
        if meta_blocked_ratio >= 0.0
        else compute_blocked_ratio(cur, stalled_samples)
    )
    blocked_dominant = rate_meta.get("blocked_dominant", "")
    blocked_threshold = eta_cfg.get("blocked_threshold", 0.6)
    eta_floor = eta_cfg.get("min_throughput_floor", 2.0)
    try:
        rows = cur.execute(
            "SELECT id, story_slug, position, story_points, status FROM tasks"
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise SystemExit(f"Failed to read tasks: {exc}")

    remaining_tasks = count_remaining_tasks(cur)
    done_statuses = NON_REMAINING_STATUSES
    total_points = 0.0
    completed_points = 0.0
    task_info: Dict[str, Dict[str, float | str]] = {}

    for row in rows:
        status = (row["status"] or "").strip().lower().replace("_", "-")
        points = parse_points(row["story_points"])
        task_key_primary = str(row["id"])
        task_info[task_key_primary] = {"points": points, "status": status}
        story_slug = (row["story_slug"] or "").strip()
        position = row["position"]
        if story_slug and position is not None:
            task_info[f"{story_slug}:{position}"] = {"points": points, "status": status}
        if status in done_statuses:
            completed_points += points
            continue
        total_points += points

    tokens_total = 0.0
    token_samples = 0
    covered_points = 0.0

    token_by_task: Dict[str, float] = {}

    if table_exists(cur, "doc_observations"):
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
    elif table_exists(cur, "task_progress"):
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
        if info:
            covered_points += float(info.get("points", 0.0))

    conn.close()

    if remaining_tasks == 0:
        print("All tasks are complete. No remaining story points.")
        return 0

    if rate <= 0:
        rate = DEFAULT_RATE
    if ewma_rate <= 0:
        ewma_rate = rate

    eta_stalled_reason: Optional[str] = None
    meta_stalled = bool(rate_meta.get("stalled"))
    meta_stall_reason = str(rate_meta.get("stall_reason") or "").strip()
    meta_frozen = bool(rate_meta.get("frozen"))
    contamination_ratio = float(rate_meta.get("contamination_ratio", 0.0))
    contamination_threshold = float(rate_meta.get("contamination_threshold", DEFAULT_CONTAMINATION_THRESHOLD))

    if meta_stalled:
        eta_stalled_reason = meta_stall_reason or "stalled"
    elif contamination_ratio >= contamination_threshold and rate_samples > 0:
        eta_stalled_reason = f"contamination {contamination_ratio * 100:.0f}%"
    elif ewma_rate > 0 and rate_samples > 0 and ewma_rate < eta_floor:
        eta_stalled_reason = f"throughput below floor ({eta_floor:.1f} SP/h)"
    elif blocked_ratio >= blocked_threshold and rate_samples >= stalled_samples:
        reason = f"blocked {blocked_ratio * 100:.0f}% of recent tasks"
        if blocked_dominant:
            reason += f" ({blocked_dominant})"
        eta_stalled_reason = reason
    elif meta_frozen and meta_stall_reason:
        eta_stalled_reason = meta_stall_reason

    effective_rate = ewma_rate if ewma_rate > 0 else rate
    total_minutes = math.ceil((total_points / effective_rate) * 60) if total_points > 0 and eta_stalled_reason is None else 0
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
    if blocked_ratio > 0:
        blocked_note = f"Recent blocked runs: {blocked_ratio * 100:.0f}%"
        if blocked_dominant:
            blocked_note += f" ({blocked_dominant})"
        print(blocked_note)
    if contamination_ratio > 0:
        print(f"Window contamination: {contamination_ratio * 100:.0f}%")
    if rate_samples > 0 and effective_rate > 0:
        sample_label = "sample" if rate_samples == 1 else "samples"
        print(
            f"Measured throughput: {fmt_float(ewma_rate)} SP/hour (based on {rate_samples} {sample_label})."
        )
    else:
        print("Using default throughput assumption: 15 SP/hour.")
    if eta_stalled_reason is not None:
        print(f"Estimated completion time: stalled ({eta_stalled_reason}).")
    else:
        print(f"Estimated completion time @{fmt_float(effective_rate)} SP/hour: {estimate_str}")

    if tokens_total > 0 and token_samples > 0:
        print(f"Tokens observed: {fmt_tokens(tokens_total)} across {token_samples} task(s).")
        if covered_points > 0:
            avg_tokens_per_point = tokens_total / covered_points
            print(
                f"Average tokens per story point: {fmt_float(avg_tokens_per_point)} tokens/SP "
                f"(based on {fmt_float(covered_points)} SP)."
            )
            estimated_tokens_hour = avg_tokens_per_point * effective_rate if effective_rate > 0 else 0.0
            if estimated_tokens_hour > 0:
                print(
                    f"Estimated token burn @{fmt_float(effective_rate)} SP/hour: "
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
