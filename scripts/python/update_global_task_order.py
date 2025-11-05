#!/usr/bin/env python3
"""Compute a cross-story task order and persist it on the tasks table."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import sqlite3
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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


def _toposort(nodes: Iterable[str], edges: Iterable[Tuple[str, str]]) -> List[str]:
    nodes_list = list(dict.fromkeys(nodes))
    indegree: Dict[str, int] = defaultdict(int)
    adjacency: Dict[str, List[str]] = defaultdict(list)

    for src, dst in edges:
        if src == dst:
            continue
        adjacency[src].append(dst)
        indegree[dst] += 1
        indegree.setdefault(src, indegree.get(src, 0))

    for node in nodes_list:
        indegree.setdefault(node, 0)

    queue: deque[str] = deque([node for node in nodes_list if indegree[node] == 0])
    order: List[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in adjacency.get(node, []):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(indegree):
        return nodes_list
    return order


def compute_order(db_path: Path) -> int:
    if not db_path.exists():
        raise FileNotFoundError(f"Task database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    _ensure_global_order_column(cur)
    _ensure_metadata_column(cur)

    rows = cur.execute(
        """
        SELECT id, task_id, story_slug, position, status, story_id, story_title, epic_key, epic_title
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
    binder_root = Path(".gpt-creator/cache/task-binder")
    edges.extend(_load_dependencies_from_binder(binder_root, tasks_by_key))

    base_order = sorted(
        nodes,
        key=lambda key: (
            _normalize(tasks_by_key[key]["story_slug"]).lower(),
            _normalize(tasks_by_key[key]["task_id"]).lower(),
            tasks_by_key[key]["position"],
        ),
    )

    topo = _toposort(base_order, edges)

    now = dt.datetime.utcnow().isoformat() + "Z"

    cur.execute("UPDATE tasks SET global_order = 0 WHERE global_order <> 0")
    cur.execute("UPDATE tasks SET global_order_updated_at = ?", (now,))

    for index, key in enumerate(topo, start=1):
        row = tasks_by_key.get(key)
        if not row:
            continue
        cur.execute(
            "UPDATE tasks SET global_order = ?, global_order_updated_at = ? WHERE id = ?",
            (index, now, row["id"]),
        )

    conn.commit()
    conn.close()
    return len(topo)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute and persist the global task order.")
    parser.add_argument("db_path", type=Path, help="Path to the tasks SQLite database.")
    args = parser.parse_args()

    total = compute_order(args.db_path)
    print(f"Computed global order for {total} task(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
