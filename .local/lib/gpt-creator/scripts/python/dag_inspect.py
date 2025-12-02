#!/usr/bin/env python3
"""DAG inspection utilities for gpt-creator (validate/next/why)."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

DONE_STATUSES = {
    "complete",
    "completed",
    "completed-no-changes",
    "skipped-already-complete",
}


def load_yaml(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    if yaml is not None:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return None
    return parse_simple_yaml(path)


def parse_simple_yaml(path: Path) -> Optional[Dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    data: Dict[str, object] = {}
    current_section: Optional[str] = None
    current_node: Optional[str] = None
    current_policy: Optional[str] = None

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(stripped)

        if indent == 0:
            current_node = None
            current_policy = None
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "story":
                data["story"] = value.strip('"')
                current_section = None
            elif key == "nodes":
                data["nodes"] = {}
                current_section = "nodes"
            elif key == "edges":
                data["edges"] = []
                current_section = "edges"
            elif key == "policies":
                data["policies"] = {}
                current_section = "policies"
            else:
                current_section = None
        elif indent == 2:
            if current_section == "nodes":
                if stripped.endswith(":"):
                    node_key = stripped[:-1].strip()
                    if not node_key:
                        return None
                    nodes = data.setdefault("nodes", {})
                    if not isinstance(nodes, dict):
                        return None
                    nodes[node_key] = {}
                    current_node = node_key
                else:
                    return None
            elif current_section == "edges":
                if stripped.startswith("-"):
                    inner = stripped[1:].strip()
                    if inner.startswith("[") and inner.endswith("]"):
                        parts = [part.strip().strip('"') for part in inner[1:-1].split(",")]
                        if len(parts) == 2:
                            edges = data.setdefault("edges", [])
                            if not isinstance(edges, list):
                                return None
                            edges.append(parts)
                    else:
                        return None
            elif current_section == "policies":
                policies = data.setdefault("policies", {})
                if not isinstance(policies, dict):
                    return None
                if stripped.endswith(":"):
                    policy_key = stripped[:-1].strip()
                    policies[policy_key] = []
                    current_policy = policy_key
                elif stripped.startswith("-") and current_policy:
                    value = stripped[1:].strip().strip('"')
                    policies.setdefault(current_policy, []).append(value)
        elif indent == 4 and current_section == "nodes" and current_node:
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            nodes = data.get("nodes")
            if not isinstance(nodes, dict):
                return None
            node_meta = nodes.get(current_node, {})
            if not isinstance(node_meta, dict):
                return None
            node_meta[key.strip()] = value.strip().strip('"')
            nodes[current_node] = node_meta

    return data if data else None


def validate_story_dag(project_root: Path, story_slug: str) -> Tuple[bool, List[str]]:
    dag_path = project_root / ".gpt-creator" / "dag" / f"{story_slug}.yaml"
    errors: List[str] = []
    if not dag_path.exists():
        errors.append(f"DAG file missing: {dag_path}")
        return False, errors
    raw = load_yaml(dag_path)
    if raw is None:
        errors.append(f"Failed to parse YAML for {dag_path}")
        return False, errors

    nodes = raw.get("nodes")
    edges = raw.get("edges") or []
    if not isinstance(nodes, dict) or not nodes:
        errors.append(f"{dag_path}: 'nodes' must be a non-empty mapping")
        return False, errors

    node_keys: Set[str] = set()
    for key, meta in nodes.items():
        if not isinstance(key, str):
            errors.append(f"{dag_path}: invalid node key {key!r}")
            continue
        norm = key.strip().upper()
        if not re.match(r"^T\d{2,}$", norm):
            errors.append(f"{dag_path}: node '{key}' must follow TNN format (e.g., T01)")
        if norm in node_keys:
            errors.append(f"{dag_path}: duplicate node key {norm}")
        node_keys.add(norm)
        if not isinstance(meta, dict):
            errors.append(f"{dag_path}: node {key} metadata must be a mapping")
            continue
        if not meta.get("title"):
            errors.append(f"{dag_path}: node {key} missing title")
        if not meta.get("kind"):
            errors.append(f"{dag_path}: node {key} missing kind")

    adjacency: Dict[str, Set[str]] = defaultdict(set)
    indegree: Dict[str, int] = {node: 0 for node in node_keys}

    for entry in edges:
        if not isinstance(entry, Sequence) or len(entry) != 2:
            errors.append(f"{dag_path}: invalid edge entry {entry!r}")
            continue
        src = str(entry[0]).strip().upper()
        dst = str(entry[1]).strip().upper()
        if src not in node_keys:
            errors.append(f"{dag_path}: edge references unknown node {src}")
            continue
        if dst not in node_keys:
            errors.append(f"{dag_path}: edge references unknown node {dst}")
            continue
        if dst in adjacency[src]:
            continue
        adjacency[src].add(dst)
        indegree[dst] += 1

    # Cycle detection via Kahn's algorithm
    queue = deque(sorted(node_keys - {node for node, deg in indegree.items() if deg > 0}))
    visited = 0
    local_indegree = indegree.copy()
    while queue:
        node = queue.popleft()
        visited += 1
        for child in adjacency.get(node, ()):
            local_indegree[child] -= 1
            if local_indegree[child] == 0:
                queue.append(child)

    if visited != len(node_keys):
        errors.append(f"{dag_path}: cycle detected in DAG (visited {visited} of {len(node_keys)} nodes)")

    return len(errors) == 0, errors


def fetch_tasks(
    db_path: Path,
    story_filter: Optional[str] = None,
) -> Dict[str, Dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    stories: Dict[str, Dict] = {}
    try:
        rows = cur.execute(
            """
            SELECT story_slug, story_id, story_title, epic_key, epic_title, sequence
              FROM stories
             ORDER BY sequence ASC, story_slug ASC
            """
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return {}

    slug_filter = (story_filter or "").strip().lower()

    for row in rows:
        slug = (row["story_slug"] or "").strip()
        if not slug:
            continue
        if slug_filter and slug.lower() != slug_filter and (row["story_id"] or "").strip().lower() != slug_filter:
            continue
        stories[slug] = {
            "sequence": int(row["sequence"] or 0),
            "story_id": (row["story_id"] or "").strip(),
            "story_title": (row["story_title"] or "").strip(),
            "epic_key": (row["epic_key"] or "").strip(),
            "epic_title": (row["epic_title"] or "").strip(),
            "tasks": [],
        }

    if not stories:
        conn.close()
        return {}

    for slug in stories.keys():
        try:
            rows = cur.execute(
                """
                SELECT position, task_id, title, status, status_reason
                  FROM tasks
                 WHERE story_slug = ?
                 ORDER BY position ASC
                """,
                (slug,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for task in rows:
            stories[slug]["tasks"].append(
                {
                    "position": int(task["position"]),
                    "task_id": (task["task_id"] or "").strip(),
                    "title": (task["title"] or "").strip(),
                    "status": (task["status"] or "").strip(),
                    "status_reason": (task["status_reason"] or "").strip(),
                }
            )

    conn.close()
    return stories


def list_ready(stories: Dict[str, Dict]) -> None:
    if not stories:
        print("No stories or tasks found.")
        return

    for slug, meta in stories.items():
        tasks = meta.get("tasks", [])
        ready = []
        blocked = []
        for task in tasks:
            status = task["status"].lower()
            if status in DONE_STATUSES:
                continue
            identifier = task["task_id"] or f"{slug}:pos{task['position']}"
            label = f"{identifier} — {task['title'] or '(untitled)'}"
            if status.startswith("blocked-dependency("):
                blocked.append((label, task["status_reason"] or status))
            elif status == "pending":
                ready.append(label)

        print(f"Story {slug} — {meta.get('story_title', '')}".strip())
        if ready:
            print("  Ready tasks:")
            for item in ready:
                print(f"    • {item}")
        else:
            print("  Ready tasks: (none)")

        if blocked:
            print("  Blocked tasks:")
            for label, reason in blocked:
                print(f"    • {label}")
                if reason:
                    print(f"      ↳ {reason}")
        print()


def explain_task(db_path: Path, task_ref: str) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    lookup = (task_ref or "").strip()
    if not lookup:
        print("Task reference required.", file=sys.stderr)
        return 1

    try:
        row = cur.execute(
            """
            SELECT story_slug, task_id, title, status, status_reason
              FROM tasks
             WHERE LOWER(task_id) = ?
            """,
            (lookup.lower(),),
        ).fetchone()
    except sqlite3.OperationalError:
        conn.close()
        print("Tasks table not found in database.", file=sys.stderr)
        return 1

    if row is None and ":" in lookup:
        story_slug, _, pos = lookup.partition(":")
        if pos.startswith("pos"):
            try:
                position = int(pos[3:])
            except ValueError:
                position = None
            if position is not None:
                row = cur.execute(
                    """
                    SELECT story_slug, task_id, title, status, status_reason
                      FROM tasks
                     WHERE story_slug = ? AND position = ?
                    """,
                    (story_slug, position),
                ).fetchone()

    if row is None:
        suffix = lookup.upper()
        if not suffix.startswith("T"):
            suffix = "T" + suffix
        row = cur.execute(
            """
            SELECT story_slug, task_id, title, status, status_reason
              FROM tasks
             WHERE task_id LIKE ?
            """,
            (f"%{suffix}",),
        ).fetchone()

    conn.close()

    if row is None:
        print(f"No task found for reference '{lookup}'.", file=sys.stderr)
        return 1

    task_id = (row["task_id"] or "").strip() or "(no id)"
    story_slug = (row["story_slug"] or "").strip()
    title = (row["title"] or "").strip()
    status = (row["status"] or "").strip()
    reason = (row["status_reason"] or "").strip()

    print(f"Task:   {task_id}")
    print(f"Story:  {story_slug}")
    print(f"Title:  {title or '(untitled)'}")
    print(f"Status: {status or 'unknown'}")
    if reason:
        print(f"Reason: {reason}")

    if status.lower().startswith("blocked-dependency(") and reason.startswith("dag:auto"):
        segments = reason.split(":", 1)[-1].strip()
        if segments:
            print(f"Details: {segments}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="dag_inspect", add_help=False)
    parser.add_argument("command", choices=("validate", "next", "why"))
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--story")
    parser.add_argument("--task")
    parser.add_argument("--db")
    parser.add_argument("--help", action="store_true")
    args, extras = parser.parse_known_args()

    if args.help:
        if args.command == "validate":
            print("usage: dag_inspect validate [--project-root PATH] [--story SLUG]")
        elif args.command == "next":
            print("usage: dag_inspect next [--project-root PATH] [--story SLUG] --db PATH")
        else:
            print("usage: dag_inspect why [--project-root PATH] --db PATH --task ID")
        return 0

    project_root = Path(args.project_root).resolve()
    if args.command == "validate":
        story = args.story or (extras[0] if extras else "")
        targets: List[str]
        if story:
            targets = [story]
        else:
            dag_dir = project_root / ".gpt-creator" / "dag"
            targets = [path.stem for path in dag_dir.glob("*.yaml")]
        failures = 0
        for slug in sorted(set(targets)):
            ok, problems = validate_story_dag(project_root, slug)
            if ok:
                print(f"[ok] {slug}")
            else:
                print(f"[fail] {slug}")
                for issue in problems:
                    print(f"  - {issue}")
                failures += 1
        return 0 if failures == 0 else 1

    db_path = Path(args.db or (extras[0] if extras else ""))
    if not db_path:
        print("--db PATH is required.", file=sys.stderr)
        return 1
    if not db_path.exists():
        print(f"Tasks database not found: {db_path}", file=sys.stderr)
        return 1

    if args.command == "next":
        stories = fetch_tasks(db_path, args.story)
        list_ready(stories)
        return 0

    if args.command == "why":
        task_ref = args.task or (extras[0] if extras else "")
        return explain_task(db_path, task_ref)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
