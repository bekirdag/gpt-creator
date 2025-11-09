#!/usr/bin/env python3
"""Estimate remaining work based on story points and throughput metadata."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


DEFAULT_RATE = 15.0
DONE_STATUS_PREFIXES = (
    "complete",
    "completed",
    "done",
    "skipped",
    "skip",
)
IN_PROGRESS_PREFIXES = (
    "in-progress",
    "in progress",
)
DEFAULT_CONTAMINATION_THRESHOLD = 0.2
RECENT_SAMPLE_LIMIT = 10
STATUS_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

ANSI_RESET = "\033[0m"
AUX_HEADER_COLOR = "1;38;5;111"
PRIMARY_HEADER_COLOR = "1;38;5;214"
TITLE_COLOR = "1;38;5;39"
ANSI_RE = re.compile(r"\x1B\[[0-9;]*m")


def color_enabled_from_env(env_value: str, default: bool) -> bool:
    mode = env_value.strip().lower()
    if mode == "always":
        return True
    if mode == "never":
        return False
    return default


def color_text(style: str, text: str) -> str:
    return f"\033[{style}m{text}{ANSI_RESET}"


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def gradient_color(pct: float) -> int:
    pct = max(0.0, min(100.0, pct))
    if pct <= 50.0:
        return int(196 + (pct / 50.0) * (220 - 196))
    return int(220 - ((pct - 50.0) / 50.0) * (220 - 46))


def gradient_bar(pct: float, width: int = 28) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round((pct / 100.0) * width))
    filled = max(0, min(width, filled))
    empty = width - filled
    color_code = gradient_color(pct)
    if filled:
        filled_block = color_text(f"38;5;{color_code}", "█" * filled)
    else:
        filled_block = ""
    percentage = color_text(f"38;5;{color_code}", f"{pct:5.1f}%")
    return f"[{filled_block}{'─' * empty}] {percentage}"


def boxed_header_lines(title: str, *, colorized: bool, min_width: int = 50) -> tuple[str, str, str]:
    visible_title = title.strip()
    content_plain = f"  {visible_title}"
    inner_width = max(min_width, len(strip_ansi(content_plain)) + 2)
    top = "╭" + "─" * inner_width + "╮"
    bottom = "╰" + "─" * inner_width + "╯"
    if len(strip_ansi(content_plain)) > inner_width:
        content_plain = content_plain[:inner_width]
    padding = inner_width - len(strip_ansi(content_plain))
    line = f"│{content_plain}{' ' * padding}│"
    if colorized:
        top = color_text(PRIMARY_HEADER_COLOR, top)
        bottom = color_text(PRIMARY_HEADER_COLOR, bottom)
        colored_title = color_text(TITLE_COLOR, visible_title)
        line = line.replace(visible_title, colored_title, 1)
    return top, line, bottom


def estimate_cache_dir(project_root: Path) -> Path:
    return project_root / ".gpt-creator" / "cache" / "estimate"


def purge_estimate_cache(cache_path: Path) -> None:
    try:
        if cache_path.exists():
            shutil.rmtree(cache_path)
    except OSError:
        pass


def cache_key_for(
    db_path: Path,
    recent_label: str,
    scope: str,
    warn_floor: float | None,
    color_variant: str,
) -> str:
    payload = f"{db_path.resolve()}|{recent_label}|{scope}|{warn_floor or 'auto'}|{color_variant}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def compute_runs_mtime(project_root: Path) -> float:
    runs_dir = project_root / ".gpt-creator" / "staging" / "plan" / "work" / "runs"
    latest = 0.0
    try:
        entries = list(runs_dir.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime > latest:
            latest = mtime
    return latest


def load_cached_output(cache_file: Path, *, db_mtime: float, runs_mtime: float, version: int = 1) -> Optional[str]:
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("version") != version:
        return None
    if abs(float(data.get("db_mtime", 0.0)) - db_mtime) > 1e-6:
        return None
    if abs(float(data.get("runs_mtime", 0.0)) - runs_mtime) > 1e-6:
        return None
    return str(data.get("output") or "")


def save_cached_output(
    cache_file: Path,
    *,
    output: str,
    db_mtime: float,
    runs_mtime: float,
    version: int = 1,
) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps(
                {
                    "version": version,
                    "db_mtime": db_mtime,
                    "runs_mtime": runs_mtime,
                    "output": output,
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def resolve_sample_limit(limit: Optional[int]) -> Optional[int]:
    if limit is None:
        return None
    return max(int(limit), RECENT_SAMPLE_LIMIT)


def describe_recent_window(limit: Optional[int]) -> str:
    if limit is None:
        return "all recorded tasks"
    resolved = resolve_sample_limit(limit)
    if resolved is None:
        return ""
    label = "task" if resolved == 1 else "tasks"
    return f"last {resolved} {label}"


def normalize_status(value: str) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = cleaned.replace("_", "-").replace(" ", "-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned


def coerce_status(value: str, fallback: str = "") -> str:
    status = normalize_status(value)
    if not status:
        return normalize_status(fallback)
    return status


def is_done_status(value: str) -> bool:
    status = coerce_status(value)
    if not status:
        return False
    tokens = [status]
    tokenised = [token for token in STATUS_TOKEN_SPLIT_RE.split(status) if token]
    if tokenised:
        tokens.extend(tokenised)
    for prefix in DONE_STATUS_PREFIXES:
        for candidate in tokens:
            if candidate.startswith(prefix):
                return True
    return False


def status_is_in_progress(value: str) -> bool:
    status = coerce_status(value)
    if not status:
        return False
    if status == "in-progress":
        return True
    for prefix in IN_PROGRESS_PREFIXES:
        prefix_norm = normalize_status(prefix)
        if prefix_norm and status.startswith(prefix_norm):
            return True
    return False


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


def column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    try:
        info = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return False
    needle = (column or "").strip().lower()
    for entry in info:
        name = str(entry[1] or "").strip().lower()
        if name == needle:
            return True
    return False


def fetch_recent_productive_samples(
    cursor: sqlite3.Cursor,
    limit: Optional[int] = RECENT_SAMPLE_LIMIT,
    *,
    scope: str = "project",
    project_root: Optional[Path] = None,
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if not table_exists(cursor, "metric_samples"):
        return [], []
    resolved_limit = resolve_sample_limit(limit)
    include_project_root = column_exists(cursor, "metric_samples", "project_root")
    select_fields = [
        "task_key",
        "story_slug",
        "task_position",
        "sp_delivered",
        "duration_seconds",
        "tokens_total",
        "occurred_at",
    ]
    if include_project_root:
        select_fields.append("project_root")
    sql = f"""
        SELECT {', '.join(select_fields)}
          FROM metric_samples
         WHERE sp_delivered IS NOT NULL
           AND sp_delivered > 0
         ORDER BY occurred_at DESC
    """
    try:
        if resolved_limit is None:
            rows = cursor.execute(sql).fetchall()
        else:
            rows = cursor.execute(f"{sql} LIMIT ?", (int(resolved_limit),)).fetchall()
    except sqlite3.DatabaseError:
        return [], []
    all_rows = list(rows)
    if scope != "project" or project_root is None:
        return all_rows, all_rows
    target_root = str(project_root.resolve())
    scoped_rows: list[sqlite3.Row] = []
    for row in all_rows:
        if "project_root" not in row.keys():
            scoped_rows.append(row)
            continue
        row_root = (row["project_root"] or "").strip()
        if not row_root:
            scoped_rows.append(row)
            continue
        if row_root == target_root:
            scoped_rows.append(row)
    return scoped_rows, all_rows


def fetch_progress_status_map(cur: sqlite3.Cursor) -> Dict[str, Dict[str, Any]]:
    if not table_exists(cur, "task_progress"):
        return {}
    columns = {
        str(entry[1] or "").strip().lower()
        for entry in cur.execute("PRAGMA table_info(task_progress)")
    }
    fields = ["task_id", "status"]
    if "progress_state" in columns:
        fields.append("progress_state")
    if "story_slug" in columns:
        fields.append("story_slug")
    if "task_position" in columns:
        fields.append("task_position")
    if "run_stamp" in columns:
        fields.append("run_stamp")
    if "occurred_at" in columns:
        fields.append("occurred_at")
    if "updated_at" in columns:
        fields.append("updated_at")

    sql = f"SELECT {', '.join(fields)} FROM task_progress ORDER BY id"
    overrides: Dict[str, Dict[str, Any]] = {}
    try:
        rows = cur.execute(sql).fetchall()
    except sqlite3.DatabaseError:
        return overrides

    for row in rows:
        status_candidate = None
        if "progress_state" in row.keys():
            status_candidate = row["progress_state"]
        if not status_candidate:
            status_candidate = row["status"]
        status_norm = coerce_status(status_candidate)
        if not status_norm:
            continue
        metadata = {
            "status": status_norm,
            "run_stamp": row["run_stamp"] if "run_stamp" in row.keys() else "",
            "occurred_at": row["occurred_at"] if "occurred_at" in row.keys() else "",
            "updated_at": row["updated_at"] if "updated_at" in row.keys() else "",
        }
        task_id_value = row["task_id"]
        if task_id_value is not None:
            overrides[str(task_id_value)] = metadata
        if "story_slug" in row.keys() and "task_position" in row.keys():
            slug = row["story_slug"]
            position = row["task_position"]
            if slug and position is not None:
                overrides[f"{slug}:{int(position)}"] = metadata
    return overrides


def fetch_progress_story_points_map(cur: sqlite3.Cursor) -> Dict[str, float]:
    if not table_exists(cur, "task_progress"):
        return {}
    if not column_exists(cur, "task_progress", "story_points"):
        return {}
    mapping: Dict[str, float] = {}
    try:
        rows = cur.execute(
            "SELECT task_id, story_slug, task_position, story_points "
            "FROM task_progress "
            "WHERE story_points IS NOT NULL "
            "ORDER BY id"
        ).fetchall()
    except sqlite3.DatabaseError:
        return mapping
    for entry in rows:
        points = parse_points(entry["story_points"])
        if points <= 0:
            continue
        task_id_value = str(entry["task_id"] or "").strip()
        if task_id_value:
            mapping[task_id_value] = points
        slug = str(entry["story_slug"] or "").strip()
        position = entry["task_position"]
        if slug and position is not None:
            mapping[f"{slug}:{int(position)}"] = points
    return mapping


SKIP_PROGRESS_OVERRIDES = {"verified", "noop-accepted"}


def apply_detected_statuses(db_path: Path, detections: list[Dict[str, Any]]) -> int:
    if not detections:
        return 0
    try:
        from update_task_state import update_task_state as _update_task_state
    except Exception:
        return 0

    applied = 0
    for entry in detections:
        story_slug = entry.get("story_slug")
        position = entry.get("position")
        if not story_slug or position is None:
            continue
        try:
            _update_task_state(
                db_path,
                str(story_slug),
                str(position),
                "complete",
                entry.get("run_stamp") or "detected",
                timestamp_override=entry.get("occurred_at") or entry.get("updated_at"),
            )
            applied += 1
        except Exception:
            continue
    return applied


def determine_effective_status(
    base_status: str,
    task_row: sqlite3.Row,
    progress_overrides: Dict[str, Dict[str, Any]],
    has_task_progress_state: bool,
    *,
    include_last_apply_status: bool = False,
    include_last_verify_status: bool = False,
) -> tuple[str, list[str], list[str], str, Optional[str]]:
    candidate_keys: list[str] = []
    if "id" in task_row.keys():
        candidate_keys.append(str(task_row["id"]))
    if "task_id" in task_row.keys():
        text_id = str(task_row["task_id"] or "").strip()
        if text_id:
            candidate_keys.append(text_id)
    if {"story_slug", "position"}.issubset(task_row.keys()):
        slug = str(task_row["story_slug"] or "").strip()
        position = task_row["position"]
        if slug and position is not None:
            candidate_keys.append(f"{slug}:{int(position)}")

    candidates: list[tuple[str, str, Optional[str]]] = []
    for key in candidate_keys:
        override = progress_overrides.get(key)
        status_value = None
        if isinstance(override, dict):
            status_value = override.get("status")
        elif override:
            status_value = override
        if status_value:
            candidates.append((status_value, "override", key))

    progress_value = ""
    if has_task_progress_state and "progress_state" in task_row.keys():
        raw_progress = task_row["progress_state"] or ""
        if raw_progress and str(raw_progress).strip():
            progress_value = raw_progress
            candidates.append((raw_progress, "progress_state", None))

    candidates.append((base_status, "base", None))

    if include_last_apply_status and "last_apply_status" in task_row.keys():
        apply_status = task_row["last_apply_status"]
        if apply_status and str(apply_status).strip():
            candidates.append((apply_status, "last_apply_status", None))

    if include_last_verify_status and "last_verify_status" in task_row.keys():
        verify_status = task_row["last_verify_status"]
        if verify_status and str(verify_status).strip():
            candidates.append((verify_status, "last_verify_status", None))

    base_normalized = coerce_status(base_status, "pending") or "pending"
    effective_status = base_normalized
    effective_origin = "base"
    effective_source_key: Optional[str] = None

    for value, origin, origin_key in candidates:
        candidate_normalized = coerce_status(value, "")
        if not candidate_normalized:
            continue
        if origin == "progress_state":
            if candidate_normalized in SKIP_PROGRESS_OVERRIDES:
                continue
        effective_status = candidate_normalized
        effective_origin = origin
        effective_source_key = origin_key
        break

    normalized_candidates: list[str] = []
    seen: set[str] = set()
    for value, _, _ in candidates:
        candidate_normalized = coerce_status(value, "")
        if candidate_normalized and candidate_normalized not in seen:
            normalized_candidates.append(candidate_normalized)
            seen.add(candidate_normalized)
    if base_normalized not in seen:
        normalized_candidates.append(base_normalized)

    return effective_status, normalized_candidates, candidate_keys, effective_origin, effective_source_key


def fmt_float(value: float) -> str:
    if math.isclose(value, round(value), rel_tol=1e-9, abs_tol=1e-9):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_tokens(value: float) -> str:
    return f"{int(round(value)):,}"


def fmt_number(value: float) -> str:
    if math.isclose(value, round(value), rel_tol=1e-9, abs_tol=1e-9):
        return f"{int(round(value)):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def print_section(title: str, rows: list[tuple[str, str]]) -> None:
    visible_rows = [
        (label, value)
        for label, value in rows
        if value is not None and str(value).strip()
    ]
    if not visible_rows:
        return
    print(title)
    print("=" * len(title))
    label_width = max(len(label) for label, _ in visible_rows)
    for label, value in visible_rows:
        print(f"{label:<{label_width}}  {value}")
    print()


def estimate(
    db_path: Path,
    recent_task_limit: Optional[int] = RECENT_SAMPLE_LIMIT,
    *,
    scope: str = "project",
    warn_threshold: Optional[float] = None,
    apply_detections: bool = False,
    project_root_override: Optional[Path] = None,
    colorize_output: bool = False,
) -> int:
    project_root = project_root_override or infer_project_root(db_path)
    scope_normalized = (scope or "project").strip().lower()
    if scope_normalized not in {"project", "all"}:
        scope_normalized = "project"
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
    warn_floor = eta_floor
    if warn_threshold is not None:
        try:
            warn_floor = max(0.0, float(warn_threshold))
        except (TypeError, ValueError):
            warn_floor = eta_floor
    meta_stalled = bool(rate_meta.get("stalled"))
    meta_stall_reason = str(rate_meta.get("stall_reason") or "").strip()
    meta_frozen = bool(rate_meta.get("frozen"))
    contamination_ratio = float(rate_meta.get("contamination_ratio", 0.0))
    contamination_threshold = float(rate_meta.get("contamination_threshold", DEFAULT_CONTAMINATION_THRESHOLD))
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
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise SystemExit(f"Failed to read tasks: {exc}")

    progress_overrides = fetch_progress_status_map(cur)
    progress_story_points = fetch_progress_story_points_map(cur)
    remaining_tasks = 0
    total_tasks_count = 0
    effective_completed_tasks = 0
    total_points = 0.0
    completed_points = 0.0
    completed_tasks_missing_points = 0
    task_info: Dict[str, Dict[str, float | str]] = {}
    canonical_completed_count = 0
    canonical_in_progress = 0
    canonical_pending = 0
    pending_detection_map: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        total_tasks_count += 1
        base_status = row["status"] or ""
        canonical_status_norm = coerce_status(base_status, "")
        canonical_done = is_done_status(canonical_status_norm)
        if canonical_done:
            canonical_completed_count += 1
        elif status_is_in_progress(canonical_status_norm):
            canonical_in_progress += 1
        else:
            canonical_pending += 1

        points = parse_points(row["story_points"])
        if points <= 0 and include_last_story_points and "last_story_points" in row.keys():
            fallback_last = parse_points(row["last_story_points"])
            if fallback_last > 0:
                points = fallback_last
        (
            effective_status,
            candidate_statuses,
            candidate_keys,
            effective_origin,
            effective_source_key,
        ) = determine_effective_status(
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
        for candidate in [effective_status, *candidate_statuses, coerce_status(base_status)]:
            candidate_norm = coerce_status(candidate, "") if candidate is not None else ""
            if not candidate_norm:
                continue
            if candidate_norm not in status_options:
                status_options.append(candidate_norm)
        if not status_options:
            status_options.append("pending")
        resolved_status = ""
        for candidate in status_options:
            if is_done_status(candidate):
                resolved_status = candidate
                break
        if not resolved_status:
            resolved_status = status_options[0]
        is_done = is_done_status(resolved_status)
        task_key_primary = str(row["id"])
        task_info[task_key_primary] = {"points": points, "status": resolved_status}
        story_slug = (row["story_slug"] or "").strip()
        position = row["position"]
        if story_slug and position is not None:
            task_info[f"{story_slug}:{position}"] = {"points": points, "status": resolved_status}
        task_id_value = (row["task_id"] or "").strip()
        if task_id_value:
            task_info[task_id_value] = {"points": points, "status": resolved_status}
        if is_done:
            effective_completed_tasks += 1
            completed_points += points
            if points <= 0:
                completed_tasks_missing_points += 1
            if not canonical_done and effective_origin == "override":
                detection_key = task_id_value or (
                    f"{story_slug}:{position}" if story_slug and position is not None else task_key_primary
                )
                if detection_key not in pending_detection_map:
                    override_candidate = progress_overrides.get(effective_source_key or detection_key)
                    override_meta = override_candidate if isinstance(override_candidate, dict) else {}
                    pending_detection_map[detection_key] = {
                        "task_key": detection_key,
                        "task_id": task_id_value,
                        "story_slug": story_slug,
                        "position": int(position) if position is not None else None,
                        "run_stamp": override_meta.get("run_stamp"),
                        "occurred_at": override_meta.get("occurred_at"),
                        "updated_at": override_meta.get("updated_at"),
                    }
            continue
        remaining_tasks += 1
        total_points += points

    pending_detections = list(pending_detection_map.values())
    detection_pending_count = len(pending_detections)

    recent_window_descriptor = describe_recent_window(recent_task_limit)
    scoped_recent_samples, total_recent_samples = fetch_recent_productive_samples(
        cur,
        recent_task_limit,
        scope=scope_normalized,
        project_root=project_root,
    )
    recent_samples = scoped_recent_samples
    recent_sample_count = len(recent_samples)
    recent_window_total = len(total_recent_samples)
    window_out_of_scope = max(recent_window_total - recent_sample_count, 0)
    computed_contamination_ratio = (
        (window_out_of_scope / recent_window_total) if recent_window_total > 0 else 0.0
    )
    if scope_normalized == "project" and recent_window_total > 0:
        contamination_ratio = computed_contamination_ratio

    tokens_total = 0.0
    token_samples = 0
    covered_points = 0.0
    using_recent_velocity = False

    if recent_samples:
        recent_points_total = 0.0
        recent_duration_seconds = 0.0
        for sample in recent_samples:
            sp_value = max(float(sample["sp_delivered"] or 0.0), 0.0)
            duration_value = float(sample["duration_seconds"] or 0.0)
            tokens_value = float(sample["tokens_total"] or 0.0)
            recent_points_total += sp_value
            if duration_value > 0:
                recent_duration_seconds += max(duration_value, 0.0)
            if tokens_value > 0:
                tokens_total += tokens_value
                token_samples += 1
                covered_points += sp_value
        if recent_points_total > 0 and recent_duration_seconds > 0:
            recent_rate = recent_points_total / (recent_duration_seconds / 3600.0)
            if recent_rate > 0:
                rate = recent_rate
                ewma_rate = recent_rate
                rate_samples = recent_sample_count
                using_recent_velocity = True
    else:
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
            if info and is_done_status(str(info.get("status", ""))):
                covered_points += float(info.get("points", 0.0))

    conn.close()

    if remaining_tasks == 0:
        print("All tasks are complete. No remaining story points.")
        return 0

    if rate <= 0:
        rate = DEFAULT_RATE
    if ewma_rate <= 0:
        ewma_rate = rate

    effective_rate = ewma_rate if ewma_rate > 0 else rate
    eta_stalled_reason: Optional[str] = None
    eta_warning_reason: Optional[str] = None

    if meta_stalled:
        reason = meta_stall_reason or "stalled"
        if reason.lower().startswith("throughput"):
            eta_warning_reason = reason
        else:
            eta_stalled_reason = reason
    elif contamination_ratio >= contamination_threshold and rate_samples > 0:
        eta_stalled_reason = f"contamination {contamination_ratio * 100:.0f}%"
    elif effective_rate > 0 and rate_samples > 0 and effective_rate < warn_floor:
        eta_warning_reason = f"throughput below floor ({warn_floor:.1f} SP/h)"
    elif blocked_ratio >= blocked_threshold and rate_samples >= stalled_samples:
        reason = f"blocked {blocked_ratio * 100:.0f}% of recent tasks"
        if blocked_dominant:
            reason += f" ({blocked_dominant})"
        eta_stalled_reason = reason
    elif meta_frozen and meta_stall_reason:
        if meta_stall_reason.lower().startswith("throughput"):
            eta_warning_reason = meta_stall_reason
        else:
            eta_stalled_reason = meta_stall_reason

    if eta_stalled_reason and "throughput" in eta_stalled_reason.lower() and effective_rate >= warn_floor:
        eta_stalled_reason = None
    if eta_warning_reason and "throughput" in eta_warning_reason.lower() and effective_rate >= warn_floor:
        eta_warning_reason = None

    total_minutes = (
        math.ceil((total_points / effective_rate) * 60)
        if total_points > 0 and eta_stalled_reason is None and effective_rate > 0
        else 0
    )
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

    applied_detections = 0
    if apply_detections and pending_detections:
        applied_detections = apply_detected_statuses(db_path, pending_detections)

    canonical_remaining = canonical_in_progress + canonical_pending

    summary_rows = [
        ("Completed tasks (canonical)", f"{canonical_completed_count:,}"),
        ("Completed tasks (effective)", f"{effective_completed_tasks:,}"),
        ("Completed story points", fmt_number(completed_points)),
    ]
    remaining_detections = max(detection_pending_count - applied_detections, 0)
    if detection_pending_count > 0:
        summary_rows.append(("Detections pending apply", f"{remaining_detections:,}"))
    if applied_detections > 0:
        summary_rows.append(("Detections applied", f"{applied_detections:,}"))

    if completed_tasks_missing_points > 0:
        summary_rows.append(
            ("Completed tasks without points", f"{completed_tasks_missing_points:,}")
        )
    summary_rows.extend(
        [
            ("In-progress (canonical)", f"{canonical_in_progress:,}"),
            ("Pending (canonical)", f"{canonical_pending:,}"),
            ("Remaining (canonical)", f"{canonical_remaining:,}"),
            ("Remaining tasks (effective)", f"{remaining_tasks:,}"),
            ("Total tasks", f"{total_tasks_count:,}"),
            ("Remaining story points", fmt_number(total_points)),
        ]
    )
    if eta_stalled_reason is not None:
        summary_rows.append(("Estimated completion", f"Stalled ({eta_stalled_reason})"))
    else:
        summary_rows.append(
            ("Estimated completion", f"{estimate_str} @{fmt_float(effective_rate)} SP/hour")
        )
    if not colorize_output:
        print_section("Remaining Work Summary", summary_rows)

    throughput_rows: list[tuple[str, str]] = []
    if rate_samples > 0 and effective_rate > 0:
        if using_recent_velocity:
            sample_label = "task" if rate_samples == 1 else "tasks"
            throughput_rows.append(
                ("Throughput basis", f"Last {rate_samples} {sample_label}")
            )
            throughput_rows.append(
                ("Effective throughput", f"{fmt_float(effective_rate)} SP/hour (recent window)")
            )
        else:
            sample_label = "run" if rate_samples == 1 else "runs"
        throughput_rows.append(
            ("Throughput basis", f"Measured from {rate_samples} {sample_label}")
        )
        throughput_rows.append(
            ("Effective throughput", f"{fmt_float(effective_rate)} SP/hour (EWMA)")
        )
    if using_recent_velocity and recent_window_descriptor:
        base_value = throughput_rows[0][1]
        if recent_window_descriptor.lower() != base_value.lower():
            throughput_rows[0] = (
                throughput_rows[0][0],
                f"{base_value} (window: {recent_window_descriptor})",
            )
    else:
        throughput_rows.append(
            ("Throughput basis", f"Default assumption ({fmt_float(DEFAULT_RATE)} SP/hour)")
        )
        throughput_rows.append(
            ("Effective throughput", f"{fmt_float(effective_rate)} SP/hour")
        )
    if recent_window_total > 0:
        throughput_rows.append(
            (
                "Throughput window",
                f"{recent_window_total} tasks (project {recent_sample_count}, out-of-scope {window_out_of_scope})",
            )
        )
    if eta_stalled_reason is not None:
        throughput_rows.append(("Run status", f"Stalled ({eta_stalled_reason})"))
    elif eta_warning_reason is not None:
        throughput_rows.append(("Run status", f"Warning ({eta_warning_reason})"))
    if blocked_ratio > 0:
        blocked_value = f"{blocked_ratio * 100:.0f}% of recent runs"
        if blocked_dominant:
            blocked_value += f" ({blocked_dominant})"
        throughput_rows.append(("Blocked signal", blocked_value))
    if contamination_ratio > 0:
        throughput_rows.append(
            ("Window contamination", f"{contamination_ratio * 100:.0f}%")
        )
    if not colorize_output:
        print_section("Throughput", throughput_rows)

    token_rows: list[tuple[str, str]] = []
    if tokens_total > 0 and token_samples > 0:
        basis_note = ""
        if recent_sample_count and recent_window_descriptor:
            basis_note = f" ({recent_window_descriptor})"
        token_rows.append(
            ("Observed tokens", f"{fmt_tokens(tokens_total)} across {token_samples} task(s){basis_note}")
        )
        if covered_points > 0:
            avg_tokens_per_point = tokens_total / covered_points
            token_rows.append(
                (
                    "Average tokens per story point",
                    f"{fmt_number(avg_tokens_per_point)} tokens/SP (based on {fmt_number(covered_points)} SP)",
                )
            )
            estimated_tokens_hour = (
                avg_tokens_per_point * effective_rate if effective_rate > 0 else 0.0
            )
            if estimated_tokens_hour > 0:
                token_rows.append(
                    (
                        "Estimated token burn",
                        f"{fmt_tokens(estimated_tokens_hour)} tokens/hour @{fmt_float(effective_rate)} SP/hour",
                    )
                )
            projected_remaining = (
                avg_tokens_per_point * total_points if total_points > 0 else 0.0
            )
            if projected_remaining > 0:
                token_rows.append(
                    (
                        "Projected remaining tokens",
                        f"{fmt_tokens(projected_remaining)} tokens for {fmt_number(total_points)} SP",
                    )
                )
        else:
            token_rows.append(
                (
                    "Average tokens per story point",
                    "Insufficient data (no story points recorded on tokenized tasks)",
                )
            )
    else:
        token_rows.append(
            (
                "Status",
                "Token usage data unavailable; run work-on-tasks to capture token telemetry.",
            )
        )
    if not colorize_output:
        print_section("Token Telemetry", token_rows)

    avg_tokens_per_point = (tokens_total / covered_points) if covered_points > 0 else 0.0
    estimated_tokens_hour = (
        avg_tokens_per_point * effective_rate if avg_tokens_per_point > 0 and effective_rate > 0 else 0.0
    )
    projected_remaining_tokens = (
        avg_tokens_per_point * total_points if avg_tokens_per_point > 0 and total_points > 0 else 0.0
    )

    if colorize_output:
        context = {
            "completed_canonical": canonical_completed_count,
            "completed_effective": effective_completed_tasks,
            "completed_story_points": completed_points,
            "detections_pending": remaining_detections,
            "detections_applied": applied_detections,
            "in_progress_canonical": canonical_in_progress,
            "pending_canonical": canonical_pending,
            "remaining_canonical": canonical_remaining,
            "remaining_effective": remaining_tasks,
            "total_tasks": total_tasks_count,
            "remaining_story_points": total_points,
            "estimate_display": (
                f"Stalled ({eta_stalled_reason})" if eta_stalled_reason else f"{estimate_str} @{fmt_float(effective_rate)} SP/hour"
            ),
            "eta_stalled_reason": eta_stalled_reason,
            "eta_warning_reason": eta_warning_reason,
            "effective_rate": effective_rate,
            "using_recent_velocity": using_recent_velocity,
            "recent_sample_count": recent_sample_count,
            "rate_samples": rate_samples,
            "recent_window_total": recent_window_total,
            "window_out_of_scope": window_out_of_scope,
            "contamination_ratio": contamination_ratio,
            "blocked_ratio": blocked_ratio,
            "blocked_dominant": blocked_dominant,
            "token_samples": token_samples,
            "tokens_total": tokens_total,
            "avg_tokens_per_point": avg_tokens_per_point,
            "estimated_tokens_hour": estimated_tokens_hour,
            "projected_remaining_tokens": projected_remaining_tokens,
            "default_rate": DEFAULT_RATE,
        }
        render_color_estimate(context)
        return 0

    return 0


def render_color_estimate(ctx: Dict[str, Any]) -> None:
    print()
    top, body, bottom = boxed_header_lines("GPT-Creator :: Project Estimate Summary", colorized=True)
    print(top)
    print(body)
    print(bottom)
    print()

    summary_header = color_text(AUX_HEADER_COLOR, "📊 Remaining Work Summary")
    print(summary_header)
    print("────────────────────────────────────────────")
    fmt = fmt_number
    green = lambda text: color_text("1;32", text)
    cyan = lambda text: color_text("1;36", text)
    yellow = lambda text: color_text("1;33", text)
    white = lambda text: color_text("1;37", text)
    magenta = lambda text: color_text("1;35", text)
    red = lambda text: color_text("1;31", text)

    print(f"• Completed tasks (canonical):       {green(fmt(ctx['completed_canonical']))}")
    print(f"• Completed tasks (effective):       {green(fmt(ctx['completed_effective']))}")
    print(f"• Completed story points:            {green(fmt(ctx['completed_story_points']))}")
    if ctx.get("detections_pending"):
        print(f"• Detections pending apply:          {yellow(fmt(ctx['detections_pending']))}")
    if ctx.get("detections_applied"):
        print(f"• Detections applied:                {cyan(fmt(ctx['detections_applied']))}")
    print(f"• In-progress (canonical):           {cyan(fmt(ctx['in_progress_canonical']))}")
    print(f"• Pending (canonical):               {white(fmt(ctx['pending_canonical']))}")
    print(f"• Remaining (canonical):             {white(fmt(ctx['remaining_canonical']))}")
    print(f"• Remaining tasks (effective):       {white(fmt(ctx['remaining_effective']))}")
    print(f"• Total tasks:                       {white(fmt(ctx['total_tasks']))}")
    print(f"• Remaining story points:            {red(fmt(ctx['remaining_story_points']))}")
    print(f"• Estimated completion:              ⏱️  {magenta(ctx['estimate_display'])}")
    print()

    throughput_header = color_text(AUX_HEADER_COLOR, "⚙️ Throughput")
    print(throughput_header)
    print("────────────────────────────────────────────")
    rate_display = fmt_float(ctx["effective_rate"])
    if ctx["using_recent_velocity"]:
        basis_text = cyan(f"Last {ctx['recent_sample_count']} task(s)")
        rate_text = green(f"{rate_display} SP/h")
        print(f"• Basis: {basis_text}")
        print(f"• Effective throughput: {rate_text} (recent window)")
    else:
        basis = "run" if ctx["rate_samples"] == 1 else "runs"
        basis_text = cyan(f"Measured from {ctx['rate_samples']} {basis}")
        rate_text = green(f"{rate_display} SP/h")
        print(f"• Basis: {basis_text}")
        print(f"• Effective throughput (EWMA): {rate_text}")

    window_total = ctx.get("recent_window_total", 0)
    if window_total:
        project_count = ctx.get("recent_sample_count", 0)
        out_of_scope = ctx.get("window_out_of_scope", 0)
        print(f"• Window: {white(f'{window_total} tasks')} (project {project_count} | out-of-scope {out_of_scope})")

    if ctx.get("eta_stalled_reason"):
        status_line = red(f"⛔  Stalled ({ctx['eta_stalled_reason']})")
    elif ctx.get("eta_warning_reason"):
        status_line = yellow(f"⚠️  Warning ({ctx['eta_warning_reason']})")
    else:
        status_line = green("OK")
    print(f"• Run status: {status_line}")

    contamination_ratio = ctx.get("contamination_ratio", 0.0) * 100
    if contamination_ratio > 0:
        print(f"• Window contamination: {yellow(f'{contamination_ratio:.0f}%')}")
    blocked_ratio = ctx.get("blocked_ratio", 0.0) * 100
    if blocked_ratio > 0:
        suffix = f" ({ctx['blocked_dominant']})" if ctx.get("blocked_dominant") else ""
        print(f"• Blocked signal: {yellow(f'{blocked_ratio:.0f}% of recent runs{suffix}')}")
    print()

    tokens_header = color_text(AUX_HEADER_COLOR, "🔢 Token Telemetry")
    print(tokens_header)
    print("────────────────────────────────────────────")
    if ctx.get("tokens_total") and ctx.get("token_samples"):
        print(f"• Observed tokens:            {cyan(fmt_tokens(ctx['tokens_total']))} across {ctx['token_samples']} task(s)")
        if ctx.get("avg_tokens_per_point"):
            avg_tokens_display = f"{fmt_number(ctx['avg_tokens_per_point'])} tokens/SP"
            print(f"• Avg tokens / SP:            {white(avg_tokens_display)}")
        if ctx.get("estimated_tokens_hour"):
            burn = fmt_tokens(ctx["estimated_tokens_hour"])
            rate_str = fmt_float(ctx["effective_rate"])
            print(
                f"• Est. token burn:            {red(burn)} tokens/h @{green(rate_str + ' SP/h')}"
            )
        if ctx.get("projected_remaining_tokens"):
            print(
                f"• Projected remaining tokens: {magenta(fmt_tokens(ctx['projected_remaining_tokens']))} for {fmt(ctx['remaining_story_points'])} SP"
            )
    else:
        print("• Status: Token usage data unavailable; run work-on-tasks to capture token telemetry.")
    print()
def parse_recent_tasks_arg(raw: str) -> Optional[int]:
    text = str(raw or "").strip().lower()
    if text in {"", "default"}:
        return RECENT_SAMPLE_LIMIT
    if text in {"all", "everything", "full"}:
        return None
    try:
        value = int(text, 10)
    except ValueError:
        raise SystemExit(f"Invalid --recent-tasks value: {raw!r}. Expected a positive integer or 'all'.")
    if value <= 0:
        raise SystemExit("--recent-tasks must be a positive integer or 'all'.")
    return value


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Estimate remaining work from throughput data.")
    parser.add_argument("db_path", help="Path to the tasks SQLite database.")
    parser.add_argument(
        "--recent-tasks",
        dest="recent_tasks",
        default=str(RECENT_SAMPLE_LIMIT),
        help="Number of recent tasks to use for throughput metrics (use 'all' for entire history).",
    )
    parser.add_argument(
        "--scope",
        choices=("project", "all"),
        default="project",
        help="Limit throughput window to the current project (default) or include all recorded samples.",
    )
    parser.add_argument(
        "--apply-detections",
        action="store_true",
        help="Apply detected completions from run logs to the canonical backlog before reporting.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the estimate cache and recompute metrics from scratch.",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Purge cached estimate data before computing the report.",
    )
    parser.add_argument(
        "--warn-threshold",
        type=float,
        default=None,
        help="Override the throughput warning threshold in story points per hour.",
    )
    parser.add_argument(
        "--color",
        action="store_true",
        help="Force colorized output even when stdout is not a TTY.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colorized output.",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise SystemExit(f"Tasks database not found: {db_path}")
    recent_limit = parse_recent_tasks_arg(args.recent_tasks)
    if args.color and args.no_color:
        raise SystemExit("--color and --no-color cannot be used together.")
    color_enabled = args.color or (not args.no_color and sys.stdout.isatty())
    project_root = infer_project_root(db_path)
    cache_dir_path = estimate_cache_dir(project_root)
    if args.reindex:
        purge_estimate_cache(cache_dir_path)

    recent_label = "all" if recent_limit is None else str(recent_limit)
    db_mtime = 0.0
    try:
        db_mtime = db_path.stat().st_mtime
    except OSError:
        db_mtime = 0.0
    runs_mtime = compute_runs_mtime(project_root)
    use_cache = not args.no_cache and not args.apply_detections
    color_variant = "color" if color_enabled else "plain"
    cache_file = cache_dir_path / (
        f"{cache_key_for(db_path, recent_label, args.scope, args.warn_threshold, color_variant)}.json"
    )

    if use_cache:
        cached_output = load_cached_output(cache_file, db_mtime=db_mtime, runs_mtime=runs_mtime)
        if cached_output:
            sys.stdout.write(cached_output)
            return

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = estimate(
            db_path,
            recent_limit,
            scope=args.scope,
            warn_threshold=args.warn_threshold,
            apply_detections=args.apply_detections,
            project_root_override=project_root,
            colorize_output=color_enabled,
        )
    output_text = buffer.getvalue()
    sys.stdout.write(output_text)

    if exit_code == 0 and use_cache:
        save_cached_output(cache_file, output=output_text, db_mtime=db_mtime, runs_mtime=runs_mtime)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
