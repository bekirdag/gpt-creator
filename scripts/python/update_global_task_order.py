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
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Set

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


def _break_cycles_with_lowest_first(
    adjacency: Dict[str, Set[str]],
    indegree: Dict[str, int],
    task_meta: Dict[str, Dict[str, Any]],
    nodes: List[str],
) -> None:
    """Within each SCC create a deterministic forward chain."""
    scc_list = _sccs(adjacency, nodes)
    for comp in scc_list:
        is_cycle = len(comp) > 1 or any(member in adjacency.get(member, ()) for member in comp)
        if not is_cycle:
            continue
        ordered = sorted(comp, key=lambda k: (task_meta.get(k, {}).get("display_sort") or k))
        positions = {name: idx for idx, name in enumerate(ordered)}
        for u in list(comp):
            for v in list(adjacency.get(u, ())):
                if v == u:
                    adjacency[u].discard(v)
                elif v in positions and positions[u] > positions[v]:
                    if v in adjacency[u]:
                        adjacency[u].discard(v)
                        indegree[v] = max(0, indegree.get(v, 0) - 1)
        for i in range(len(ordered) - 1):
            u, v = ordered[i], ordered[i + 1]
            if v not in adjacency[u]:
                adjacency[u].add(v)
                indegree[v] = indegree.get(v, 0) + 1


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


def _select_edge_to_drop(
    comp: List[str],
    adjacency: Dict[str, Set[str]],
    task_meta: Dict[str, Dict[str, Any]],
) -> Optional[Tuple[str, str]]:
    best: Optional[Tuple[str, str, Tuple]] = None
    for u in comp:
        for v in adjacency.get(u, ()):
            if v not in comp:
                continue
            meta_u = task_meta.get(u, {})
            meta_v = task_meta.get(v, {})
            story_u = meta_u.get("story_sort")
            story_v = meta_v.get("story_sort")
            cross_story = (story_u or "") != (story_v or "")
            descending = (meta_u.get("display_sort") or u) > (meta_v.get("display_sort") or v)
            score = (
                0 if cross_story else 1,
                0 if descending else 1,
                meta_u.get("display_sort") or u,
                meta_v.get("display_sort") or v,
            )
            if best is None or score < best[2]:
                best = (u, v, score)
    if best:
        return best[0], best[1]
    return None


def _decycle_graph(
    adjacency: Dict[str, Set[str]],
    indegree: Dict[str, int],
    task_meta: Dict[str, Dict[str, Any]],
    nodes: List[str],
) -> List[Tuple[str, str]]:
    removed: List[Tuple[str, str]] = []
    for _ in range(1000):
        scc_list = _sccs(adjacency, nodes)
        edge_removed = False
        for comp in scc_list:
            if len(comp) <= 1:
                continue
            drop = _select_edge_to_drop(comp, adjacency, task_meta)
            if not drop:
                continue
            u, v = drop
            if v in adjacency.get(u, set()):
                adjacency[u].discard(v)
                indegree[v] = max(0, indegree.get(v, 0) - 1)
                removed.append((u, v))
                edge_removed = True
                break
        if not edge_removed:
            break
    return removed
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

    adjacency: Dict[str, Set[str]] = defaultdict(set)
    missing_dependency_edges = 0
    missing_dependency_targets: Set[str] = set()

    for blocker, target in edges:
        if blocker == target:
            continue
        blocker_known = blocker in tasks_by_key
        target_known = target in tasks_by_key
        if not blocker_known or not target_known:
            missing_dependency_edges += 1
            if target_known:
                missing_dependency_targets.add(target)
            continue
        adjacency[blocker].add(target)

    for key in nodes:
        adjacency.setdefault(key, set())

    known_nodes: Set[str] = set(nodes)
    for source in list(adjacency.keys()):
        invalid = {dest for dest in adjacency[source] if dest not in known_nodes}
        if invalid:
            adjacency[source].difference_update(invalid)

    if missing_dependency_edges:
        print(
            f"[order] Info: dropped {missing_dependency_edges} dependency edge(s) referencing missing tasks.",
            file=sys.stderr,
        )

    indegree: Dict[str, int] = {key: 0 for key in nodes}
    for outs in adjacency.values():
        for dest in outs:
            indegree[dest] = indegree.get(dest, 0) + 1

    def _pretty_label(row: sqlite3.Row) -> str:
        task_label = _normalize(row["task_id"])
        if task_label:
            return task_label
        story_slug = _normalize(row["story_slug"])
        try:
            position_val = int(row["position"])
        except (TypeError, ValueError):
            position_val = 0
        if story_slug:
            return f"{story_slug}:{position_val + 1}"
        return f"id#{row['id']}"

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

    removed_edges = _decycle_graph(
        adjacency=adjacency,
        indegree=indegree,
        task_meta=task_meta,
        nodes=nodes,
    )
    if removed_edges:
        def _edge_label(u: str, v: str) -> str:
            u_label = task_meta.get(u, {}).get("display_id") or u
            v_label = task_meta.get(v, {}).get("display_id") or v
            return f"{u_label}->{v_label}"

        sample_removed = ", ".join(_edge_label(a, b) for a, b in removed_edges[:5])
        print(
            f"[order] Info: removed {len(removed_edges)} cycle edge(s) prior to scheduling{': ' + sample_removed if sample_removed else ''}.",
            file=sys.stderr,
        )

    _break_cycles_with_lowest_first(
        adjacency=adjacency,
        indegree=indegree,
        task_meta=task_meta,
        nodes=nodes,
    )

    for key in nodes:
        if indegree.get(key, 0) == 0:
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

    remaining_nodes = [key for key in nodes if key not in processed]
    cycle_nodes = [key for key in remaining_nodes if indegree.get(key, 0) > 0]
    if cycle_nodes:
        sample = ", ".join(task_meta[key]["display_id"] for key in cycle_nodes[:10])
        print(
            f"[order] Warning: residual cycles after rewiring involving {len(cycle_nodes)} task(s); examples: {sample}",
            file=sys.stderr,
        )

    unscheduled = [key for key in nodes if key not in processed]
    if unscheduled:
        missing_priority = sorted(
            (key for key in unscheduled if key in missing_dependency_targets),
            key=lambda s: (task_meta.get(s, {}).get("display_sort") or s),
        )
        remaining_priority = sorted(
            (key for key in unscheduled if key not in missing_dependency_targets),
            key=lambda s: (task_meta.get(s, {}).get("display_sort") or s),
        )
        fallback = missing_priority + remaining_priority
        sample = ", ".join(task_meta[key]["display_id"] for key in fallback[:10])
        print(
            f"[order] Info: {len(fallback)} task(s) scheduled via fallback; examples: {sample}",
            file=sys.stderr,
        )
        for key in fallback:
            if key in processed:
                continue
            order.append(key)
            processed.add(key)

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
