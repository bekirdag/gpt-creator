#!/usr/bin/env python3
"""Compute a cross-story task order and persist it on the tasks table."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Set

TERMINAL_STATUSES = {
    "complete",
    "completed",
    "completed-no-changes",
    "completed_with_followup",
    "done",
    "done-with-followup",
    "done-with-review",
    "skipped",
    "skipped-already-complete",
}


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip()


def _normalize_status(value: Optional[str]) -> str:
    text = _normalize(value).lower().replace("_", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _is_terminal(status: Optional[str]) -> bool:
    normalized = _normalize_status(status)
    if not normalized:
        return False
    if normalized in TERMINAL_STATUSES:
        return True
    return normalized.startswith("completed-") or normalized.startswith("done-") or normalized.startswith("skipped-")


def _task_key(task_row: sqlite3.Row) -> str:
    task_id = _normalize(task_row["task_id"])
    if task_id:
        return task_id.lower()
    story_slug = _normalize(task_row["story_slug"]).lower()
    position = int(task_row["position"])
    return f"{story_slug}:{position + 1}"


def _parse_dep_list(raw: object) -> List[str]:
    if isinstance(raw, list):
        return [_normalize(item) for item in raw if _normalize(item)]
    if isinstance(raw, str):
        return [_normalize(part) for part in raw.replace(",", " ").split() if _normalize(part)]
    return []


def _ensure_global_order_column(cur: sqlite3.Cursor) -> None:
    info = cur.execute("PRAGMA table_info(tasks)").fetchall()
    if not any(row[1] == "global_order" for row in info):
        cur.execute("ALTER TABLE tasks ADD COLUMN global_order INTEGER NOT NULL DEFAULT 0")


def _ensure_metadata_column(cur: sqlite3.Cursor) -> None:
    info = cur.execute("PRAGMA table_info(tasks)").fetchall()
    if not any(row[1] == "global_order_updated_at" for row in info):
        cur.execute("ALTER TABLE tasks ADD COLUMN global_order_updated_at TEXT")


def _ensure_task_dependencies_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            blocker_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    cur.execute(
        """
        DELETE FROM task_dependencies
         WHERE rowid NOT IN (
           SELECT MIN(rowid) FROM task_dependencies GROUP BY task_id, blocker_id
         )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_task_dependencies_unique
          ON task_dependencies (task_id, blocker_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_task
          ON task_dependencies (task_id)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_blocker
            ON task_dependencies (blocker_id)
        """
    )


def _ensure_task_metadata_columns(cur: sqlite3.Cursor) -> None:
    info = cur.execute("PRAGMA table_info(tasks)").fetchall()
    columns = {row[1] for row in info}
    if "priority" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER")
    if "due_at" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN due_at TEXT")
    if "points" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN points REAL")


def _load_dependencies_from_db(cur: sqlite3.Cursor, known_keys: Dict[str, int]) -> List[Tuple[str, str]]:
    edges: List[Tuple[str, str]] = []
    try:
        rows = cur.execute(
            "SELECT blocker_id, task_id FROM task_dependencies WHERE blocker_id IS NOT NULL AND task_id IS NOT NULL"
        ).fetchall()
    except sqlite3.DatabaseError:
        rows = []

    for row in rows:
        blocker = _normalize(row["blocker_id"]).lower()
        target = _normalize(row["task_id"]).lower()
        if blocker in known_keys and target in known_keys:
            edges.append((blocker, target))
    return edges


def _load_dependencies_from_binder(cache_root: Path, known_keys: Dict[str, int]) -> List[Tuple[str, str]]:
    if not cache_root.exists():
        return []
    keys = ("depends_on", "depends", "requires", "blocked_by", "blocked-by", "prereq")
    edges: List[Tuple[str, str]] = []

    for path_str in glob.glob(str(cache_root / "**" / "*.json"), recursive=True):
        path = Path(path_str)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if isinstance(payload, dict) and isinstance(payload.get("task"), dict):
            payload = payload["task"]
        if not isinstance(payload, dict):
            continue

        task_id = _normalize(
            payload.get("task_id")
            or payload.get("id")
            or payload.get("slug")
        ).lower()
        if task_id not in known_keys:
            continue

        deps: List[str] = []
        for key in keys:
            if key in payload:
                deps.extend(_parse_dep_list(payload.get(key)))
        dag_data = payload.get("dag")
        if isinstance(dag_data, dict):
            deps.extend(_parse_dep_list(dag_data.get("requires")))

        for dep in deps:
            dep_norm = dep.strip().lower()
            if dep_norm and dep_norm in known_keys and dep_norm != task_id:
                edges.append((dep_norm, task_id))

    return edges


def compute_order(db_path: Path, project_root: Path) -> int:
    if not db_path.exists():
        raise FileNotFoundError(f"Task database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    _ensure_global_order_column(cur)
    _ensure_metadata_column(cur)
    _ensure_task_dependencies_table(cur)
    _ensure_task_metadata_columns(cur)

    rows = cur.execute(
        """
        SELECT id,
               task_id,
               story_slug,
               position,
               status,
               story_id,
               story_title,
               epic_key,
               epic_title,
               priority,
               due_at,
               points,
               story_points
          FROM tasks
        """
    ).fetchall()

    tasks_by_key: Dict[str, sqlite3.Row] = {}
    nodes: List[str] = []

    for row in rows:
        if _is_terminal(row["status"]):
            continue
        key = _task_key(row)
        tasks_by_key[key] = row
        nodes.append(key)

    if not nodes:
        cur.execute("UPDATE tasks SET global_order = 0")
        cur.execute("UPDATE tasks SET global_order_updated_at = ?", (dt.datetime.utcnow().isoformat() + "Z",))
        conn.commit()
        conn.close()
        return 0

    edges = _load_dependencies_from_db(cur, tasks_by_key)
    binder_root = project_root / ".gpt-creator" / "cache" / "task-binder"
    edges.extend(_load_dependencies_from_binder(binder_root, tasks_by_key))

    indegree: Dict[str, int] = {key: 0 for key in nodes}
    adjacency: Dict[str, Set[str]] = defaultdict(set)

    for blocker, target in edges:
        if blocker == target:
            continue
        if blocker not in tasks_by_key or target not in tasks_by_key:
            continue
        if target not in adjacency[blocker]:
            adjacency[blocker].add(target)
            indegree[target] += 1

    def _parse_priority(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _parse_due(value: Optional[str]) -> float:
        if not value:
            return float("inf")
        text = value.strip()
        if not text:
            return float("inf")
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return dt.datetime.fromisoformat(text).timestamp()
        except Exception:
            return float("inf")

    points_pattern = re.compile(r"[-+]?\d*\.?\d+")

    def _parse_points(primary, fallback) -> float:
        for candidate in (primary, fallback):
            if candidate is None:
                continue
            if isinstance(candidate, (int, float)):
                try:
                    val = float(candidate)
                    if val >= 0:
                        return val
                except (TypeError, ValueError):
                    continue
            if isinstance(candidate, str):
                stripped = candidate.strip()
                if not stripped:
                    continue
                match = points_pattern.search(stripped)
                if not match:
                    continue
                try:
                    val = float(match.group(0))
                    if val >= 0:
                        return val
                except ValueError:
                    continue
        return float("inf")

    READY_STATUSES = {"pending", "retryable"}

    task_meta: Dict[str, Dict[str, object]] = {}
    for key, row in tasks_by_key.items():
        status_text = _normalize_status(row["status"])
        status_ready = status_text in READY_STATUSES
        priority = _parse_priority(row["priority"])
        due_ts = _parse_due(row["due_at"])
        points_value = _parse_points(row["points"], row["story_points"])
        epic_sort = (_normalize(row["epic_key"]) or _normalize(row["epic_title"]) or "").lower()
        story_sort = _normalize(row["story_slug"]).lower()
        display_label = _normalize(row["task_id"]) or key
        task_meta[key] = {
            "row": row,
            "status": status_text,
            "ready": status_ready,
            "priority": priority,
            "due_ts": due_ts,
            "points": points_value,
            "epic_sort": epic_sort,
            "story_sort": story_sort,
            "display_id": display_label,
            "display_sort": (display_label or "").lower(),
        }

    import heapq

    heap: List[Tuple[Tuple, int, str]] = []
    counter = 0

    def push_ready(key: str) -> None:
        info = task_meta.get(key)
        if not info or not info["ready"]:
            return
        priority_tuple = (
            -int(info["priority"]),
            float(info["due_ts"]),
            float(info["points"]),
            info["epic_sort"],
            info["story_sort"],
            info["display_sort"],
        )
        nonlocal counter
        heapq.heappush(heap, (priority_tuple, counter, key))
        counter += 1

    for key in nodes:
        if indegree[key] == 0:
            push_ready(key)

    order: List[str] = []
    processed: Set[str] = set()

    while heap:
        _, _, key = heapq.heappop(heap)
        if key in processed:
            continue
        order.append(key)
        processed.add(key)
        for neighbor in adjacency.get(key, ()):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                push_ready(neighbor)

    remaining_ready = [
        key for key in nodes if key not in processed and task_meta.get(key, {}).get("ready")
    ]

    if remaining_ready:
        sample = ", ".join(task_meta[key]["display_id"] for key in remaining_ready[:10])
        print(
            f"[order] Warning: {len(remaining_ready)} task(s) could not be scheduled (cycle or missing dependency); examples: {sample}",
            file=sys.stderr,
        )

    remaining_nodes = [key for key in nodes if key not in processed]
    cycle_nodes = [key for key in remaining_nodes if indegree.get(key, 0) > 0]
    if cycle_nodes:
        sample = ", ".join(task_meta[key]["display_id"] for key in cycle_nodes[:10])
        print(
            f"[order] Warning: detected potential dependency cycle involving {len(cycle_nodes)} task(s); examples: {sample}",
            file=sys.stderr,
        )

    now = dt.datetime.utcnow().isoformat() + "Z"

    cur.execute("UPDATE tasks SET global_order = 0 WHERE global_order <> 0")
    cur.execute("UPDATE tasks SET global_order_updated_at = ?", (now,))

    for index, key in enumerate(order, start=1):
        row = tasks_by_key.get(key)
        if not row:
            continue
        cur.execute(
            "UPDATE tasks SET global_order = ?, global_order_updated_at = ? WHERE id = ?",
            (index, now, row["id"]),
        )

    conn.commit()
    conn.close()
    return len(order)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute and persist the global task order.")
    parser.add_argument("db_path", type=Path, help="Path to the tasks SQLite database.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root containing .gpt-creator cache directories (defaults to PROJECT_ROOT or cwd).",
    )
    args = parser.parse_args()

    project_root = args.project_root
    if project_root is None:
        project_root = Path(os.environ.get("PROJECT_ROOT") or os.getcwd())
    project_root = project_root.resolve()

    total = compute_order(args.db_path, project_root)
    print(f"Computed global order for {total} task(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
