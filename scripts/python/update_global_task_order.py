#!/usr/bin/env python3
"""Compute a cross-story task order and persist it on the tasks table."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import heapq
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Set

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


def _sccs(adjacency: Dict[str, Set[str]], nodes: List[str]) -> List[List[str]]:
    """Return strongly connected components using Tarjan's algorithm."""
    index = 0
    stack: List[str] = []
    on_stack: Set[str] = set()
    idx: Dict[str, int] = {}
    low: Dict[str, int] = {}
    result: List[List[str]] = []

    sys.setrecursionlimit(max(10000, len(nodes) * 2))

    def visit(v: str) -> None:
        nonlocal index
        idx[v] = index
        low[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in adjacency.get(v, ()):
            if w not in idx:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp: List[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            result.append(comp)

    for v in nodes:
        if v not in idx:
            visit(v)
    return result

_ID_TOKEN_PATTERN = re.compile(r"[A-Za-z]+|\d+")


def _id_key(task_id: str) -> Tuple[Tuple[int, object], ...]:
    """Split IDs into alpha/numeric tokens so T8 < T10."""
    tokens = _ID_TOKEN_PATTERN.findall(task_id or "")
    if not tokens:
        return ((1, ""),)
    key_parts: List[Tuple[int, object]] = []
    for token in tokens:
        if token.isdigit():
            key_parts.append((0, int(token)))
        else:
            key_parts.append((1, token.lower()))
    return tuple(key_parts)


def _stable_toposort(task_ids: Iterable[str], dep_edges: Iterable[Tuple[str, str]]) -> List[str]:
    """
    Deterministically order tasks by ID, respecting dependency edges.

    Dependencies are tuples (u, v) meaning u must come before v.
    """
    ids = list(dict.fromkeys(task_ids))
    nodes: Set[str] = set(ids)
    adjacency: Dict[str, Set[str]] = defaultdict(set)
    for blocker, target in dep_edges:
        if not blocker or not target or blocker == target:
            continue
        nodes.add(blocker)
        nodes.add(target)
        adjacency[blocker].add(target)

    for node in list(nodes):
        adjacency.setdefault(node, set())

    key_map: Dict[str, Tuple[Tuple[int, object], ...]] = {}
    for node in nodes:
        key_map[node] = _id_key(node)

    indegree: Dict[str, int] = {node: 0 for node in nodes}
    for targets in adjacency.values():
        for dest in targets:
            indegree[dest] = indegree.get(dest, 0) + 1

    # Break cycles per strongly connected component, stripping backward edges.
    for comp in _sccs(adjacency, list(nodes)):
        if len(comp) <= 1 and not any(member in adjacency.get(member, ()) for member in comp):
            continue
        ordered_comp = sorted(comp, key=lambda name: (key_map.get(name), name))
        position = {name: idx for idx, name in enumerate(ordered_comp)}
        for src in list(comp):
            for dest in list(adjacency.get(src, ())):
                if dest == src:
                    adjacency[src].discard(dest)
                    continue
                if dest in position and position[src] > position[dest]:
                    adjacency[src].discard(dest)
                    indegree[dest] = max(0, indegree.get(dest, 0) - 1)

    heap: List[Tuple[Tuple[int, object], str]] = []
    for node in nodes:
        if indegree.get(node, 0) == 0:
            heapq.heappush(heap, (key_map[node], node))

    ordered: List[str] = []
    while heap:
        _, node = heapq.heappop(heap)
        ordered.append(node)
        for dest in list(adjacency[node]):
            indegree[dest] = indegree.get(dest, 0) - 1
            if indegree[dest] == 0:
                heapq.heappush(heap, (key_map[dest], dest))
        adjacency[node].clear()

    if len(ordered) < len(nodes):
        remaining = sorted(
            (node for node in nodes if node not in ordered),
            key=lambda name: (key_map.get(name), name),
        )
        ordered.extend(remaining)

    return ordered


def _ensure_task_metadata_columns(cur: sqlite3.Cursor) -> None:
    info = cur.execute("PRAGMA table_info(tasks)").fetchall()
    columns = {row[1] for row in info}
    if "priority" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN priority INTEGER")
    if "due_at" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN due_at TEXT")
    if "points" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN points REAL")
    if "story_order" not in columns:
        cur.execute("ALTER TABLE tasks ADD COLUMN story_order INTEGER")


def _ensure_metadata_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


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


def compute_order(db_path: Path, project_root: Path, skip_if_exists: bool = False) -> Optional[int]:
    if not db_path.exists():
        raise FileNotFoundError(f"Task database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if skip_if_exists:
        existing = cur.execute("SELECT 1 FROM tasks WHERE global_order > 0 LIMIT 1").fetchone()
        if existing:
            conn.close()
            return None

    _ensure_global_order_column(cur)
    _ensure_metadata_column(cur)
    _ensure_task_dependencies_table(cur)
    _ensure_task_metadata_columns(cur)
    _ensure_metadata_table(cur)

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
        cur.execute("UPDATE tasks SET story_order = NULL")
        cur.execute("UPDATE tasks SET global_order_updated_at = ?", (dt.datetime.utcnow().isoformat() + "Z",))
        conn.commit()
        conn.close()
        return 0

    edges = _load_dependencies_from_db(cur, tasks_by_key)
    binder_root = project_root / ".gpt-creator" / "cache" / "task-binder"
    edges.extend(_load_dependencies_from_binder(binder_root, tasks_by_key))

    valid_edges: List[Tuple[str, str]] = []
    missing_dependency_edges = 0

    for blocker, target in edges:
        if blocker == target:
            continue
        blocker_known = blocker in tasks_by_key
        target_known = target in tasks_by_key
        if not (blocker_known and target_known):
            missing_dependency_edges += 1
            continue
        valid_edges.append((blocker, target))

    if missing_dependency_edges:
        print(
            f"[order] Info: dropped {missing_dependency_edges} dependency edge(s) referencing missing tasks.",
            file=sys.stderr,
        )

    order = _stable_toposort(nodes, valid_edges)

    now = dt.datetime.utcnow().isoformat() + "Z"

    cur.execute("UPDATE tasks SET global_order = 0 WHERE global_order <> 0")
    cur.execute("UPDATE tasks SET global_order_updated_at = ?", (now,))

    cur.execute("UPDATE tasks SET story_order = NULL WHERE story_order IS NOT NULL")
    current_index = 0
    story_positions: Dict[str, int] = defaultdict(int)
    for key in order:
        row = tasks_by_key.get(key)
        if not row:
            continue
        current_index += 1
        story_slug_norm = _normalize(row["story_slug"]).lower()
        story_positions[story_slug_norm] = story_positions.get(story_slug_norm, 0) + 1
        cur.execute(
            "UPDATE tasks SET global_order = ?, story_order = ?, global_order_updated_at = ? WHERE id = ?",
            (current_index, story_positions[story_slug_norm], now, row["id"]),
        )

    remaining_rows = cur.execute(
        "SELECT id FROM tasks WHERE global_order = 0 ORDER BY id"
    ).fetchall()
    for row in remaining_rows:
        current_index += 1
        cur.execute(
            "UPDATE tasks SET global_order = ?, global_order_updated_at = ? WHERE id = ?",
            (current_index, now, row["id"]),
        )

    cur.execute(
        """
        INSERT INTO metadata(key, value)
        VALUES('global_order_last_computed_at', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (now,),
    )

    marker_path = db_path.parent / "ORDERED.ok"
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(now + "\n", encoding="utf-8")
    except Exception:
        pass

    conn.commit()
    conn.close()
    return current_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute and persist the global task order.")
    parser.add_argument("db_path", type=Path, help="Path to the tasks SQLite database.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root containing .gpt-creator cache directories (defaults to PROJECT_ROOT or cwd).",
    )
    parser.add_argument(
        "--ensure",
        action="store_true",
        help="Skip recomputing if tasks already have a global order.",
    )
    args = parser.parse_args()

    project_root = args.project_root
    if project_root is None:
        project_root = Path(os.environ.get("PROJECT_ROOT") or os.getcwd())
    project_root = project_root.resolve()

    total = compute_order(args.db_path, project_root, skip_if_exists=args.ensure)
    if total is None:
        print("[order] Global task order already present; skipping.")
    else:
        print(f"Computed global order for {total} task(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
