#!/usr/bin/env python3
"""Recompute work-on-tasks throughput and token efficiency metrics."""

from __future__ import annotations

import fnmatch
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


PRODUCTIVE_STATUSES = {
    "complete",
    "complete-verified-no-diff",
    "completed-no-changes",
}

DEFAULT_EXCLUDE_PATTERNS = [
    "skip*",
    "blocked-*",
    "test-env-failed",
    "on-hold",
    "on_hold",
]
DEFAULT_WINDOW_HOURS = 6.0
DEFAULT_ALPHA = 0.3
DEFAULT_DEDUPE_MINUTES = 15
DEFAULT_RETENTION_DAYS = 7
DEFAULT_RETRY_HORIZON_MINUTES = 30
DEFAULT_STALL_FLOOR = 2.0
DEFAULT_STALL_BLOCKED_THRESHOLD = 0.6
DEFAULT_STALL_SAMPLE_LIMIT = 5
DEFAULT_CONTAMINATION_THRESHOLD = 0.2

STATUS_ALIAS_MAP = {
    "completed": "complete",
}

MIN_ELAPSED_SECONDS = 60.0
MIN_SAMPLE_DURATION = 60.0
BASELINE_SAMPLE_LIMIT = 500


def normalize_status(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = cleaned.replace("_", "-").replace(" ", "-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = STATUS_ALIAS_MAP.get(cleaned, cleaned)
    return cleaned


def normalize_pattern(pattern: str) -> str:
    cleaned = (pattern or "").strip().lower()
    cleaned = cleaned.replace("_", "-").replace(" ", "-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned


def parse_points(raw: Any) -> float:
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if not text:
        return 0.0
    normalized = text.lower().replace(",", ".")
    for token in normalized.replace("/", " ").split():
        try:
            value = float(token)
        except ValueError:
            continue
        if value > 0:
            return value
    return 0.0


def parse_timestamp(value: Optional[str]) -> Optional[float]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
    return None


def load_yaml_config(project_root: Path) -> Dict[str, Any]:
    config_path = project_root / ".gpt-creator" / "config.yml"
    if not config_path.exists():
        return {}
    text = config_path.read_text(encoding="utf-8")
    if not text.strip() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(text)  # type: ignore[attr-defined]
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def infer_project_root(db_path: Path) -> Path:
    env = os.environ.get("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    resolved = db_path.resolve()
    for parent in resolved.parents:
        if parent.name == ".gpt-creator":
            return parent.parent
    return resolved.parent


def load_metrics_config(project_root: Path) -> Dict[str, Any]:
    config_root = load_yaml_config(project_root)
    metrics_cfg = config_root.get("metrics") if isinstance(config_root, dict) else None

    window_hours = DEFAULT_WINDOW_HOURS
    alpha = DEFAULT_ALPHA
    dedupe_minutes = DEFAULT_DEDUPE_MINUTES
    retention_days = DEFAULT_RETENTION_DAYS
    retry_minutes = DEFAULT_RETRY_HORIZON_MINUTES
    stall_floor = DEFAULT_STALL_FLOOR
    blocked_threshold = DEFAULT_STALL_BLOCKED_THRESHOLD
    stall_sample_limit = DEFAULT_STALL_SAMPLE_LIMIT
    contamination_threshold = DEFAULT_CONTAMINATION_THRESHOLD
    patterns = DEFAULT_EXCLUDE_PATTERNS[:]

    if isinstance(metrics_cfg, dict):
        try:
            value = float(metrics_cfg.get("window_hours", window_hours))
            if value > 0:
                window_hours = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("alpha", alpha))
            if 0.0 < value < 1.0:
                alpha = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("dedupe_minutes", dedupe_minutes))
            if value > 0:
                dedupe_minutes = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("retry_minutes", retry_minutes))
            if value > 0:
                retry_minutes = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("stall_floor", stall_floor))
            if value >= 0:
                stall_floor = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("blocked_threshold", blocked_threshold))
            if 0.0 <= value <= 1.0:
                blocked_threshold = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("stall_samples", stall_sample_limit))
            if value > 0:
                stall_sample_limit = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("contamination_threshold", contamination_threshold))
            if 0.0 <= value < 1.0:
                contamination_threshold = value
        except (TypeError, ValueError):
            pass
        try:
            value = float(metrics_cfg.get("retention_days", retention_days))
            if value > 0:
                retention_days = value
        except (TypeError, ValueError):
            pass
        raw_patterns = metrics_cfg.get("exclude_statuses")
        if isinstance(raw_patterns, (list, tuple)):
            normalized = [normalize_pattern(str(item)) for item in raw_patterns]
            patterns = [item for item in normalized if item]

    alpha = min(max(alpha, 0.05), 0.95)
    window_seconds = max(window_hours, 0.1) * 3600.0
    dedupe_seconds = max(dedupe_minutes, 1.0) * 60.0
    retry_seconds = max(retry_minutes, 1.0) * 60.0
    retention_seconds = max(retention_days, 1.0) * 86400.0

    return {
        "window_seconds": window_seconds,
        "alpha": alpha,
        "dedupe_seconds": dedupe_seconds,
        "retention_seconds": retention_seconds,
        "exclude_patterns": patterns,
        "retry_seconds": retry_seconds,
        "stall_floor": stall_floor,
        "blocked_threshold": blocked_threshold,
        "stall_sample_limit": int(max(1, round(stall_sample_limit))),
        "contamination_threshold": contamination_threshold,
    }


def ensure_metadata_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )


def ensure_metric_tables(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metric_samples (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_key TEXT NOT NULL,
          occurred_at REAL NOT NULL,
          story_slug TEXT,
          task_position INTEGER,
          task_id TEXT,
          run_stamp TEXT,
          final_status TEXT,
          sp_delivered REAL,
          tokens_total REAL,
          tokens_retrieve REAL,
          tokens_plan REAL,
          tokens_patch REAL,
          tokens_verify REAL,
          tokens_per_sp REAL,
          hotspot_phase TEXT,
          duration_seconds REAL,
          migration_epoch INTEGER,
          base_branch TEXT,
          merged INTEGER,
          is_parent INTEGER,
          created_at REAL NOT NULL DEFAULT (strftime('%s','now')),
          updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_metric_samples_task ON metric_samples(task_key, occurred_at)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_metric_samples_time ON metric_samples(occurred_at)"
    )
    for column, definition in (
        ("migration_epoch", "INTEGER"),
        ("base_branch", "TEXT"),
        ("merged", "INTEGER"),
        ("is_parent", "INTEGER"),
    ):
        ensure_column(cur, "metric_samples", column, definition)


def set_meta(cur: sqlite3.Cursor, key: str, value: Any) -> None:
    cur.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        (key, str(value)),
    )


def meta_float(cur: sqlite3.Cursor, key: str, default: float = 0.0) -> float:
    row = cur.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
    if not row or row["value"] is None:
        return default
    try:
        return float(row["value"])
    except (TypeError, ValueError):
        return default


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def winsorize_limits(values: Sequence[float], lower_p: float = 0.05, upper_p: float = 0.95) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    ordered = sorted(values)
    n = len(ordered)
    lower_index = max(0, min(n - 1, int(math.floor(lower_p * (n - 1)))))
    upper_index = max(0, min(n - 1, int(math.floor(upper_p * (n - 1)))))
    return ordered[lower_index], ordered[upper_index]


def winsorize_value(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def normalize_branch(value: str) -> str:
    text = (value or "").strip().lower()
    if text.startswith("refs/heads/"):
        text = text[len("refs/heads/") :]
    if text.startswith("origin/"):
        text = text[len("origin/") :]
    if text.startswith("upstream/"):
        text = text[len("upstream/") :]
    return text


def branch_allows_sample(base_branch: str, merged: Any) -> bool:
    branch = normalize_branch(base_branch)
    if branch in {"main", "master"}:
        return True
    try:
        merged_flag = bool(int(merged))
    except (TypeError, ValueError):
        merged_flag = bool(merged)
    return merged_flag


def ensure_column(cur: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    if not any(row[1] == column for row in cur.fetchall()):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def fetch_current_epoch(cur: sqlite3.Cursor) -> int:
    try:
        cur.execute("PRAGMA table_info(tasks)")
    except sqlite3.DatabaseError:
        return 0
    columns = {row[1] for row in cur.fetchall()}
    if "migration_epoch" not in columns:
        return 0
    try:
        row = cur.execute("SELECT COALESCE(MAX(migration_epoch), 0) FROM tasks").fetchone()
    except sqlite3.DatabaseError:
        return 0
    return int(row[0] or 0)


def infer_is_parent_flag(row: sqlite3.Row) -> int:
    if "is_parent" in row.keys() and row["is_parent"] is not None:
        value = row["is_parent"]
        try:
            return int(bool(int(value)))
        except (TypeError, ValueError):
            return 1 if value else 0
    task_identifier = ""
    story_slug = ""
    if "task_id" in row.keys() and row["task_id"] is not None:
        task_identifier = str(row["task_id"]).strip()
    if "story_slug" in row.keys() and row["story_slug"] is not None:
        story_slug = str(row["story_slug"]).strip()
    if task_identifier and story_slug and normalize_status(task_identifier) == normalize_status(story_slug):
        return 1
    return 1


def blocked_status_bucket(status: str) -> Optional[str]:
    text = normalize_status(status)
    if not text:
        return None
    if text.startswith("blocked-"):
        return text
    if text.startswith("on-hold"):
        return "on-hold"
    if text.startswith("skip"):
        return "skip"
    if text.startswith("test-env-failed"):
        return "test-env-failed"
    return None


def compute_blocked_stats(cur: sqlite3.Cursor, sample_limit: int) -> Tuple[float, str]:
    if sample_limit <= 0:
        return 0.0, ""
    try:
        rows = cur.execute(
            "SELECT final_status FROM metric_samples ORDER BY occurred_at DESC LIMIT ?",
            (int(sample_limit),),
        ).fetchall()
    except sqlite3.DatabaseError:
        return 0.0, ""
    counts: Counter[str] = Counter()
    total = 0
    for row in rows:
        status_value = row["final_status"] if isinstance(row, sqlite3.Row) else row[0]
        bucket = blocked_status_bucket(status_value)
        if bucket:
            counts[bucket] += 1
        if status_value:
            total += 1
    if total == 0:
        return 0.0, ""
    dominant = counts.most_common(1)[0][0] if counts else ""
    ratio = sum(counts.values()) / total if total else 0.0
    return ratio, dominant


def write_metrics_files(project_root: Path, payload: Dict[str, Any]) -> None:
    metrics_dir = project_root / ".gpt-creator" / "logs" / "work-on-tasks"
    try:
        metrics_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    metrics_path = metrics_dir / "metrics.json"
    ndjson_path = metrics_dir / "metrics.ndjson"
    snapshot = {
        key: value
        for key, value in payload.items()
        if key
        in {
            "timestamp",
            "window_rate",
            "ewma",
            "effective_rate",
            "total_sp",
            "sample_count",
            "unique_tasks",
            "contamination_ratio",
            "blocked_ratio",
            "blocked_dominant",
            "stalled",
            "stall_reason",
            "tokens_per_sp",
            "stage_tokens",
            "stage_tokens_per_sp",
        }
    }
    try:
        metrics_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass
    try:
        with ndjson_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def fetch_tokens_per_sp_baseline(cur: sqlite3.Cursor) -> float:
    rows = cur.execute(
        """
        SELECT tokens_per_sp
          FROM metric_samples
         WHERE tokens_per_sp IS NOT NULL AND tokens_per_sp > 0
         ORDER BY occurred_at DESC
         LIMIT ?
        """,
        (BASELINE_SAMPLE_LIMIT,),
    ).fetchall()
    values = [float(row["tokens_per_sp"]) for row in rows if row["tokens_per_sp"] is not None]
    return percentile(values, 95.0) if values else 0.0


def status_excluded(status: str, patterns: Sequence[str]) -> bool:
    status_norm = normalize_status(status)
    for pattern in patterns:
        if fnmatch.fnmatch(status_norm, pattern):
            return True
    return False


def capture_sample(
    cur: sqlite3.Cursor,
    story_slug: str,
    position: str,
    config: Dict[str, Any],
    exclude_patterns: Sequence[str],
) -> bool:
    if not story_slug or not position:
        return False
    try:
        position_int = int(position)
    except ValueError:
        return False

    try:
        row = cur.execute(
            "SELECT * FROM tasks WHERE story_slug = ? AND position = ?",
            (story_slug, position_int),
        ).fetchone()
    except sqlite3.DatabaseError:
        return False

    if not row:
        return False

    status_norm = normalize_status(row["status"]) if "status" in row.keys() else ""
    story_points_value = parse_points(row["last_story_points"]) if "last_story_points" in row.keys() else 0.0
    if story_points_value <= 0:
        story_points_value = parse_points(row["story_points"]) if "story_points" in row.keys() else 0.0
    tokens_retrieve = float(row["last_tokens_retrieve"] or 0.0) if "last_tokens_retrieve" in row.keys() else 0.0
    tokens_plan = float(row["last_tokens_plan"] or 0.0) if "last_tokens_plan" in row.keys() else 0.0
    tokens_patch = float(row["last_tokens_patch"] or 0.0) if "last_tokens_patch" in row.keys() else 0.0
    tokens_verify = float(row["last_tokens_verify"] or 0.0) if "last_tokens_verify" in row.keys() else 0.0
    tokens_stage_total = tokens_retrieve + tokens_plan + tokens_patch + tokens_verify
    tokens_per_sp = (
        tokens_stage_total / story_points_value
        if story_points_value > 0
        else float(row["last_tokens_per_sp"] or 0.0) if "last_tokens_per_sp" in row.keys() else 0.0
    )

    hotspot_phase = normalize_status(row["last_hotspot_phase"] or "") if "last_hotspot_phase" in row.keys() else ""
    if not hotspot_phase and tokens_stage_total > 0:
        stage_pairs = [
            ("retrieve", tokens_retrieve),
            ("plan", tokens_plan),
            ("patch", tokens_patch),
            ("verify", tokens_verify),
        ]
        dominant = max(stage_pairs, key=lambda item: item[1])
        if dominant[1] > 0:
            hotspot_phase = dominant[0]

    duration_seconds = float(row["last_duration_seconds"] or 0.0) if "last_duration_seconds" in row.keys() else 0.0
    occurred_at = parse_timestamp(row["last_progress_at"]) if "last_progress_at" in row.keys() else None
    occurred_at = occurred_at or time.time()
    run_stamp = (row["last_progress_run"] or "").strip() if "last_progress_run" in row.keys() else ""
    task_id = row["task_id"] if "task_id" in row.keys() else None
    migration_epoch = int(row["migration_epoch"] or 0) if "migration_epoch" in row.keys() else 0
    base_branch = (row["base_branch"] or "").strip() if "base_branch" in row.keys() else ""
    if not base_branch:
        base_branch = "main"
    merged_flag_raw = row["merged"] if "merged" in row.keys() else None
    try:
        merged_flag = int(bool(int(merged_flag_raw)))
    except (TypeError, ValueError):
        merged_flag = 1 if merged_flag_raw else 0
    is_parent_flag = infer_is_parent_flag(row)

    if status_excluded(status_norm, exclude_patterns):
        delivered_sp = 0.0
    elif status_norm in PRODUCTIVE_STATUSES and story_points_value > 0:
        delivered_sp = story_points_value
    else:
        delivered_sp = 0.0

    task_key = f"{story_slug}:{position_int}"
    dedupe_window = config["dedupe_seconds"]
    existing = cur.execute(
        "SELECT id FROM metric_samples WHERE task_key = ? AND occurred_at >= ? ORDER BY occurred_at DESC LIMIT 1",
        (task_key, occurred_at - dedupe_window),
    ).fetchone()

    params = (
        occurred_at,
        story_slug,
        position_int,
        task_id,
        run_stamp,
        status_norm,
        delivered_sp,
        tokens_stage_total,
        tokens_retrieve,
        tokens_plan,
        tokens_patch,
        tokens_verify,
        tokens_per_sp,
        hotspot_phase,
        duration_seconds,
        migration_epoch,
        base_branch,
        merged_flag,
        is_parent_flag,
    )

    if existing:
        cur.execute(
            """
            UPDATE metric_samples
               SET occurred_at = ?,
                   story_slug = ?,
                   task_position = ?,
                   task_id = ?,
                   run_stamp = ?,
                   final_status = ?,
                   sp_delivered = ?,
                   tokens_total = ?,
                   tokens_retrieve = ?,
                   tokens_plan = ?,
                   tokens_patch = ?,
                   tokens_verify = ?,
                   tokens_per_sp = ?,
                   hotspot_phase = ?,
                   duration_seconds = ?,
                   migration_epoch = ?,
                   base_branch = ?,
                   merged = ?,
                   is_parent = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            params + (time.time(), existing["id"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO metric_samples (
              task_key,
              occurred_at,
              story_slug,
              task_position,
              task_id,
              run_stamp,
              final_status,
              sp_delivered,
              tokens_total,
              tokens_retrieve,
              tokens_plan,
              tokens_patch,
              tokens_verify,
              tokens_per_sp,
              hotspot_phase,
              duration_seconds,
              migration_epoch,
              base_branch,
              merged,
              is_parent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_key,) + params,
        )
    return True


def prune_samples(cur: sqlite3.Cursor, now_ts: float, retention_seconds: float) -> None:
    cutoff = now_ts - retention_seconds
    cur.execute("DELETE FROM metric_samples WHERE occurred_at < ?", (cutoff,))


def compute_metrics(
    cur: sqlite3.Cursor,
    config: Dict[str, Any],
    prev_ewma: float,
    now_ts: float,
    project_root: Path,
) -> Dict[str, Any]:
    window_start = now_ts - config["window_seconds"]
    rows = cur.execute(
        """
        SELECT task_key,
               story_slug,
               task_id,
               occurred_at,
               sp_delivered,
               tokens_total,
               tokens_retrieve,
               tokens_plan,
               tokens_patch,
               tokens_verify,
               tokens_per_sp,
               duration_seconds,
               final_status,
               migration_epoch,
               base_branch,
               merged,
               is_parent
          FROM metric_samples
         WHERE occurred_at >= ?
         ORDER BY occurred_at ASC
        """,
        (window_start,),
    ).fetchall()

    total_samples = len(rows)
    current_epoch = fetch_current_epoch(cur)
    retry_seconds = float(config.get("retry_seconds", DEFAULT_RETRY_HORIZON_MINUTES * 60))
    latest_by_task: Dict[str, sqlite3.Row] = {}

    for row in rows:
        status_norm = normalize_status(row["final_status"])
        sp_value = float(row["sp_delivered"] or 0.0)
        if sp_value <= 0.0:
            continue
        if status_norm not in PRODUCTIVE_STATUSES:
            continue
        migration_epoch = int(row["migration_epoch"] or 0) if "migration_epoch" in row.keys() else 0
        if current_epoch and migration_epoch and migration_epoch != current_epoch:
            continue
        base_branch = row["base_branch"] if "base_branch" in row.keys() else ""
        merged_flag = row["merged"] if "merged" in row.keys() else 0
        if not branch_allows_sample(base_branch or "main", merged_flag):
            continue
        task_key_effective = (row["task_id"] or "").strip() or (row["task_key"] or "")
        if not task_key_effective:
            task_key_effective = f"anon:{len(latest_by_task)}"
        occurred_at = float(row["occurred_at"] or now_ts)
        previous = latest_by_task.get(task_key_effective)
        if previous is not None:
            prev_ts = float(previous["occurred_at"] or now_ts)
            if occurred_at <= prev_ts:
                continue
        latest_by_task[task_key_effective] = row

    dedup_rows = sorted(latest_by_task.values(), key=lambda item: float(item["occurred_at"] or now_ts))
    contamination_ratio = 0.0
    if total_samples > 0:
        contamination_ratio = 1.0 - (len(dedup_rows) / total_samples)

    primary_by_story: Dict[str, sqlite3.Row] = {}
    for row in dedup_rows:
        slug = (row["story_slug"] or "").strip()
        if not slug:
            slug = row["task_key"] or ""
        existing = primary_by_story.get(slug)
        if existing is None:
            primary_by_story[slug] = row
        else:
            existing_sp = float(existing["sp_delivered"] or 0.0)
            candidate_sp = float(row["sp_delivered"] or 0.0)
            if candidate_sp >= existing_sp:
                primary_by_story[slug] = row

    primary_rows = sorted(primary_by_story.values(), key=lambda item: float(item["occurred_at"] or now_ts))

    def extract_values(key: str) -> List[float]:
        return [float(row[key] or 0.0) for row in primary_rows]

    tokens_total_values = extract_values("tokens_total")
    duration_values = [max(float(row["duration_seconds"] or 0.0), MIN_SAMPLE_DURATION) for row in primary_rows]
    stage_keys = {"retrieve": "tokens_retrieve", "plan": "tokens_plan", "patch": "tokens_patch", "verify": "tokens_verify"}
    stage_values: Dict[str, List[float]] = {label: extract_values(column) for label, column in stage_keys.items()}

    tokens_low, tokens_high = winsorize_limits(tokens_total_values)
    duration_low, duration_high = winsorize_limits(duration_values)
    duration_wins = [winsorize_value(value, duration_low, duration_high) for value in duration_values]
    tokens_total_wins = [winsorize_value(value, tokens_low, tokens_high) for value in tokens_total_values]

    stage_limits: Dict[str, Tuple[float, float]] = {
        label: winsorize_limits(values) for label, values in stage_values.items()
    }
    stage_totals = {
        label: sum(winsorize_value(value, *stage_limits[label]) for value in values)
        for label, values in stage_values.items()
    }

    total_sp = sum(float(row["sp_delivered"] or 0.0) for row in primary_rows)
    tokens_total = sum(tokens_total_wins)
    tokens_per_sp = tokens_total / total_sp if total_sp > 0 else 0.0

    if primary_rows:
        first_ts = float(primary_rows[0]["occurred_at"] or now_ts)
        last_ts = float(primary_rows[-1]["occurred_at"] or now_ts)
        span_seconds = max(last_ts - first_ts, MIN_ELAPSED_SECONDS)
        duration_sum = sum(duration_wins)
        span_seconds = max(span_seconds, duration_sum)
    else:
        span_seconds = 0.0

    window_rate = (total_sp / (span_seconds / 3600.0)) if span_seconds > 0 else 0.0
    alpha = config["alpha"]
    ewma = window_rate if prev_ewma <= 0 else (alpha * window_rate) + ((1 - alpha) * prev_ewma)

    stage_total_sum = sum(stage_totals.values())
    hotspot_stage = ""
    hotspot_share = 0.0
    if stage_total_sum > 0:
        hotspot_stage, hotspot_value = max(stage_totals.items(), key=lambda item: item[1])
        if hotspot_value > 0:
            hotspot_share = hotspot_value / stage_total_sum
        else:
            hotspot_stage = ""

    stage_tokens_per_sp = {
        label: (total / total_sp) if total_sp > 0 else 0.0 for label, total in stage_totals.items()
    }

    baseline_p95 = fetch_tokens_per_sp_baseline(cur)
    alert_threshold = baseline_p95 * 1.25 if baseline_p95 > 0 else 0.0
    tokens_alert = tokens_per_sp > alert_threshold > 0

    blocked_ratio, blocked_dominant = compute_blocked_stats(cur, config.get("stall_sample_limit", DEFAULT_STALL_SAMPLE_LIMIT))
    stalled = False
    stall_reason = ""
    if ewma > 0 and ewma < config.get("stall_floor", DEFAULT_STALL_FLOOR):
        stalled = True
        stall_reason = f"throughput<{config.get('stall_floor', DEFAULT_STALL_FLOOR):.1f}"
    if not stalled and blocked_ratio >= config.get("blocked_threshold", DEFAULT_STALL_BLOCKED_THRESHOLD) and len(primary_rows) >= config.get("stall_sample_limit", DEFAULT_STALL_SAMPLE_LIMIT):
        stalled = True
        stall_reason = f"blocked {blocked_ratio * 100:.0f}%"
        if blocked_dominant:
            stall_reason += f" ({blocked_dominant})"

    freeze_metrics = stalled or (contamination_ratio > config.get("contamination_threshold", DEFAULT_CONTAMINATION_THRESHOLD))
    effective_rate = ewma
    if freeze_metrics and prev_ewma > 0:
        effective_rate = prev_ewma
    elif freeze_metrics:
        effective_rate = window_rate

    metrics = {
        "window_rate": window_rate,
        "ewma": ewma,
        "effective_rate": effective_rate,
        "total_sp": total_sp,
        "span_seconds": span_seconds,
        "stage_totals": stage_totals,
        "stage_tokens_per_sp": stage_tokens_per_sp,
        "tokens_total": tokens_total,
        "tokens_per_sp": tokens_per_sp,
        "baseline_p95": baseline_p95,
        "tokens_alert": tokens_alert,
        "hotspot_stage": hotspot_stage,
        "hotspot_share": hotspot_share,
        "sample_count": len(primary_rows),
        "unique_tasks": len(dedup_rows),
        "total_samples": total_samples,
        "contamination_ratio": contamination_ratio,
        "blocked_ratio": blocked_ratio,
        "blocked_dominant": blocked_dominant,
        "stalled": stalled,
        "stall_reason": stall_reason,
        "freeze": freeze_metrics,
        "contamination_threshold": config.get("contamination_threshold", DEFAULT_CONTAMINATION_THRESHOLD),
        "updated_at": now_ts,
    }

    metrics_payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts)),
        "window_rate": window_rate,
        "ewma": ewma,
        "effective_rate": effective_rate,
        "total_sp": total_sp,
        "sample_count": len(primary_rows),
        "unique_tasks": len(dedup_rows),
        "contamination_ratio": contamination_ratio,
        "blocked_ratio": blocked_ratio,
        "blocked_dominant": blocked_dominant,
        "stalled": stalled,
        "stall_reason": stall_reason,
        "tokens_per_sp": tokens_per_sp,
        "stage_tokens": stage_totals,
        "stage_tokens_per_sp": stage_tokens_per_sp,
    }
    write_metrics_files(project_root, metrics_payload)

    return metrics


def persist_metrics(cur: sqlite3.Cursor, metrics: Dict[str, Any], config: Dict[str, Any]) -> None:
    set_meta(cur, "throughput.rate_sp_per_hour", f"{metrics['effective_rate']:.6f}")
    set_meta(cur, "throughput.productive_ewma", f"{metrics['ewma']:.6f}")
    set_meta(cur, "throughput.samples", str(metrics["sample_count"]))
    set_meta(cur, "throughput.samples_unique", str(metrics["unique_tasks"]))
    set_meta(cur, "throughput.samples_total", str(metrics["total_samples"]))
    set_meta(cur, "throughput.window_points", f"{metrics['total_sp']:.6f}")
    set_meta(cur, "throughput.window_seconds", f"{metrics['span_seconds']:.3f}")
    set_meta(cur, "throughput.blocked_ratio", f"{metrics['blocked_ratio']:.6f}")
    set_meta(cur, "throughput.blocked_dominant", metrics["blocked_dominant"] or "")
    set_meta(cur, "throughput.stalled", "1" if metrics["stalled"] else "0")
    set_meta(cur, "throughput.stalled_reason", metrics["stall_reason"] or "")
    set_meta(cur, "throughput.contamination_ratio", f"{metrics['contamination_ratio']:.6f}")
    set_meta(cur, "throughput.frozen", "1" if metrics["freeze"] else "0")
    set_meta(cur, "metrics.tokens_per_sp_avg", f"{metrics['tokens_per_sp']:.6f}")
    set_meta(cur, "metrics.tokens_per_sp_p95", f"{metrics['baseline_p95']:.6f}")
    set_meta(cur, "metrics.tokens_alert_active", "1" if metrics["tokens_alert"] else "0")
    set_meta(cur, "metrics.hotspot_stage", metrics["hotspot_stage"] or "")
    set_meta(cur, "metrics.hotspot_stage_share", f"{metrics['hotspot_share']:.6f}")
    set_meta(cur, "metrics.window_stage_tokens", json.dumps(metrics["stage_totals"], ensure_ascii=False))
    set_meta(cur, "metrics.window_stage_tokens_per_sp", json.dumps(metrics["stage_tokens_per_sp"], ensure_ascii=False))
    set_meta(cur, "metrics.window_tokens_total", f"{metrics['tokens_total']:.6f}")
    set_meta(cur, "metrics.window_hours", f"{config['window_seconds'] / 3600.0:.2f}")
    set_meta(cur, "metrics.alpha", f"{config['alpha']:.3f}")
    set_meta(cur, "metrics.exclude_statuses", json.dumps(list(config["exclude_patterns"]), ensure_ascii=False))
    set_meta(cur, "metrics.dedupe_minutes", f"{config['dedupe_seconds'] / 60.0:.2f}")
    if "retry_seconds" in config:
        set_meta(cur, "metrics.retry_minutes", f"{config['retry_seconds'] / 60.0:.2f}")
    set_meta(cur, "metrics.stall_floor", f"{config.get('stall_floor', DEFAULT_STALL_FLOOR):.3f}")
    set_meta(cur, "metrics.blocked_threshold", f"{config.get('blocked_threshold', DEFAULT_STALL_BLOCKED_THRESHOLD):.3f}")
    set_meta(cur, "metrics.stall_sample_limit", str(config.get('stall_sample_limit', DEFAULT_STALL_SAMPLE_LIMIT)))
    set_meta(cur, "metrics.contamination_threshold", f"{config.get('contamination_threshold', DEFAULT_CONTAMINATION_THRESHOLD):.3f}")
    set_meta(cur, "throughput.updated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(metrics["updated_at"])))


def format_message(metrics: Dict[str, Any]) -> Optional[str]:
    if metrics["sample_count"] == 0:
        return None
    if metrics["stalled"]:
        reason = metrics["stall_reason"] or "stalled"
        message = f"Throughput stalled ({reason})"
    else:
        message = f"Throughput {metrics['effective_rate']:.2f} SP/h"
        if metrics["window_rate"] > 0 and metrics["total_sp"] > 0:
            message += f" (window {metrics['window_rate']:.2f} over {metrics['total_sp']:.2f} SP)"

    details: List[str] = []
    if metrics["tokens_per_sp"] > 0:
        token_note = f"tokens/SP {metrics['tokens_per_sp']:.0f}"
        if metrics["tokens_alert"] and metrics["baseline_p95"] > 0:
            token_note += f" (>p95 {metrics['baseline_p95']:.0f})"
        details.append(token_note)
    if metrics["hotspot_stage"]:
        details.append(f"hotspot {metrics['hotspot_stage']} {metrics['hotspot_share'] * 100:.0f}%")
    contamination_threshold = metrics.get("contamination_threshold", DEFAULT_CONTAMINATION_THRESHOLD)
    if metrics["contamination_ratio"] > contamination_threshold:
        details.append(f"contamination {metrics['contamination_ratio'] * 100:.0f}%")
    if metrics["blocked_ratio"] > 0:
        blocked_note = f"blocked {metrics['blocked_ratio'] * 100:.0f}%"
        if metrics["blocked_dominant"]:
            blocked_note += f" ({metrics['blocked_dominant']})"
        details.append(blocked_note)
    if details:
        message += " — " + "; ".join(details)
    return message


def main() -> int:
    if len(sys.argv) < 5:
        return 1

    db_path = Path(sys.argv[1]).resolve()
    action = (sys.argv[2] or "").strip().lower()
    story_slug = sys.argv[3]
    position = sys.argv[4]

    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.DatabaseError:
        return 1

    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ensure_metadata_table(cur)
    ensure_metric_tables(cur)

    project_root = infer_project_root(db_path)
    config = load_metrics_config(project_root)

    now_ts = time.time()
    message: Optional[str] = None

    updated = False
    if action == "task-complete":
        updated = capture_sample(cur, story_slug, position, config, config["exclude_patterns"])

    if action in {"task-complete", "checkpoint", "flush"}:
        prune_samples(cur, now_ts, config["retention_seconds"])
        prev_ewma = meta_float(cur, "throughput.productive_ewma", 0.0)
        metrics = compute_metrics(cur, config, prev_ewma, now_ts, project_root)
        persist_metrics(cur, metrics, config)
        message = format_message(metrics)
    elif action == "init":
        set_meta(cur, "metrics.window_hours", f"{config['window_seconds'] / 3600.0:.2f}")
        set_meta(cur, "metrics.alpha", f"{config['alpha']:.3f}")
        set_meta(cur, "metrics.exclude_statuses", json.dumps(list(config["exclude_patterns"]), ensure_ascii=False))
        set_meta(cur, "metrics.dedupe_minutes", f"{config['dedupe_seconds'] / 60.0:.2f}")

    conn.commit()
    conn.close()

    if message:
        print(message)
    return 0 if (action != "task-complete" or updated) else 0


if __name__ == "__main__":
    raise SystemExit(main())
