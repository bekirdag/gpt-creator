#!/usr/bin/env python3
"""Plan story task execution order with DAG and readiness gates."""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - PyYAML is expected to be available
    yaml = None


RUN_STAMP = "dag-scheduler"
DONE_STATUSES = {
    "complete",
    "completed",
    "completed-no-changes",
    "skipped-already-complete",
}
BLOCK_PREFIX = "blocked-dependency("

KIND_PRIORITY = {
    "ADR": 0,
    "SPEC": 0,
    "SCHEMA": 1,
    "INSTRUMENT": 2,
    "API": 3,
    "UI": 4,
    "TEST": 5,
    "RUNBOOK": 6,
}

GATE_KIND_SCOPE = {
    "schema_applied": {"SCHEMA", "API", "INSTRUMENT", "UI", "TEST", "RUNBOOK"},
    "api_contract_exists": {"API", "UI", "TEST", "RUNBOOK"},
    # gates without an explicit scope apply to every task
}


@dataclass
class TaskRecord:
    id: int
    position: int
    task_id: str
    title: str
    status: str
    status_reason: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]

    def status_lower(self) -> str:
        return (self.status or "").strip().lower()

    def dag_key(self) -> Optional[str]:
        task_id = (self.task_id or "").strip()
        if not task_id:
            return None
        match = re.search(r"(T\d{2,})$", task_id.upper())
        if match:
            return match.group(1)
        return None


@dataclass
class DagConfig:
    story: str
    nodes: Dict[str, Dict[str, str]]
    edges: List[Tuple[str, str]]
    ready_requires: List[str]
    task_id_map: Dict[str, List[str]]


def _slug_norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _load_yaml(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    if yaml is not None:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            return None
    return _parse_simple_yaml(path)


def _parse_simple_yaml(path: Path) -> Optional[Dict]:
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


def load_dag(project_root: Path, story_slug: str) -> Optional[DagConfig]:
    dag_path = project_root / ".gpt-creator" / "dag" / f"{story_slug}.yaml"
    raw = _load_yaml(dag_path)
    if not raw:
        return None

    nodes = raw.get("nodes") or {}
    edges = raw.get("edges") or []
    policies = raw.get("policies") or {}
    task_id_map_raw = raw.get("task_id_map") or {}

    if not isinstance(nodes, dict):
        nodes = {}
    if not isinstance(edges, Sequence):
        edges = []

    ready_requires = policies.get("ready_requires", []) if isinstance(policies, dict) else []
    if not isinstance(ready_requires, Sequence):
        ready_requires = []
    ready_requires = [str(item).strip() for item in ready_requires if str(item).strip()]

    task_id_map: Dict[str, List[str]] = {}
    if isinstance(task_id_map_raw, dict):
        for key, value in task_id_map_raw.items():
            if not isinstance(key, str):
                continue
            values: List[str]
            if isinstance(value, str):
                values = [value]
            elif isinstance(value, Sequence):
                values = [str(v).strip() for v in value if str(v).strip()]
            else:
                continue
            task_id_map[key.upper()] = [item.lower() for item in values if item]

    normalized_nodes: Dict[str, Dict[str, str]] = {}
    for key, meta in nodes.items():
        if not isinstance(key, str):
            continue
        norm_key = key.upper()
        if not isinstance(meta, dict):
            meta = {}
        normalized_nodes[norm_key] = {
            "title": str(meta.get("title") or "").strip(),
            "kind": str(meta.get("kind") or "").strip().upper(),
        }

    normalized_edges: List[Tuple[str, str]] = []
    for entry in edges:
        if isinstance(entry, Sequence) and len(entry) == 2:
            src, dst = str(entry[0]).strip().upper(), str(entry[1]).strip().upper()
            if src and dst:
                normalized_edges.append((src, dst))

    return DagConfig(
        story=str(raw.get("story") or story_slug),
        nodes=normalized_nodes,
        edges=normalized_edges,
        ready_requires=ready_requires,
        task_id_map=task_id_map,
    )


def _map_task_to_node(task: TaskRecord, dag: DagConfig) -> Optional[str]:
    candidate = task.dag_key()
    if candidate and candidate in dag.nodes:
        return candidate
    task_id_norm = (task.task_id or "").strip().lower()
    if not task_id_norm:
        return None
    for node, mapped in dag.task_id_map.items():
        if task_id_norm in mapped and node in dag.nodes:
            return node
    return None


def _fetch_story_tasks(cur: sqlite3.Cursor, story_slug: str, story_id: str) -> List[TaskRecord]:
    def query(slug_value: str) -> List[TaskRecord]:
        rows = cur.execute(
            """
            SELECT id, position, task_id, title, status, status_reason, started_at, completed_at
              FROM tasks
             WHERE LOWER(COALESCE(story_slug, "")) = ?
             ORDER BY position ASC
            """,
            (slug_value.lower(),),
        ).fetchall()
        return [
            TaskRecord(
                id=int(row["id"]),
                position=int(row["position"]),
                task_id=str(row["task_id"] or ""),
                title=str(row["title"] or ""),
                status=str(row["status"] or ""),
                status_reason=str(row["status_reason"]) if row["status_reason"] is not None else None,
                started_at=str(row["started_at"]) if row["started_at"] is not None else None,
                completed_at=str(row["completed_at"]) if row["completed_at"] is not None else None,
            )
            for row in rows
        ]

    slug_clean = (story_slug or "").strip()
    story_id_clean = (story_id or "").strip()

    if slug_clean:
        tasks = query(slug_clean)
        if tasks:
            return tasks

    if story_id_clean:
        rows = cur.execute(
            """
            SELECT id, position, task_id, title, status, status_reason, started_at, completed_at, story_slug
              FROM tasks
             WHERE LOWER(COALESCE(story_id, "")) = ?
             ORDER BY position ASC
            """,
            (story_id_clean.lower(),),
        ).fetchall()
        if rows:
            tasks = [
                TaskRecord(
                    id=int(row["id"]),
                    position=int(row["position"]),
                    task_id=str(row["task_id"] or ""),
                    title=str(row["title"] or ""),
                    status=str(row["status"] or ""),
                    status_reason=str(row["status_reason"]) if row["status_reason"] is not None else None,
                    started_at=str(row["started_at"]) if row["started_at"] is not None else None,
                    completed_at=str(row["completed_at"]) if row["completed_at"] is not None else None,
                )
                for row in rows
            ]
            if slug_clean:
                cur.execute(
                    "UPDATE tasks SET story_slug = ? WHERE LOWER(COALESCE(story_id, \"\")) = ?",
                    (slug_clean, story_id_clean.lower()),
                )
            return tasks

    slug_key = _slug_norm(slug_clean)
    if slug_key and slug_key != slug_clean.lower():
        tasks = query(slug_key)
        if tasks and slug_clean:
            cur.execute(
                "UPDATE tasks SET story_slug = ? WHERE LOWER(COALESCE(story_slug, \"\")) = ?",
                (slug_clean, slug_key),
            )
        return tasks

    return []


def _kind_priority(kind: str) -> int:
    return KIND_PRIORITY.get(kind.upper(), 50)


def _topological_order(
    dag: DagConfig,
    node_to_task: Dict[str, TaskRecord],
    children_map: Dict[str, Set[str]],
) -> List[str]:
    active_nodes = set(node_to_task.keys())
    in_degree: Dict[str, int] = {}
    for node in active_nodes:
        in_degree[node] = 0
    for src, dst in dag.edges:
        if src in active_nodes and dst in active_nodes:
            in_degree[dst] += 1

    queue = [node for node, deg in in_degree.items() if deg == 0]
    order: List[str] = []

    while queue:
        queue.sort(
            key=lambda name: (
                _kind_priority(dag.nodes.get(name, {}).get("kind", "")),
                -len(children_map.get(name, ())),
                node_to_task[name].position,
                name,
            )
        )
        node = queue.pop(0)
        order.append(node)
        for child in children_map.get(node, ()):
            if child in in_degree:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        in_degree.pop(node, None)

    if len(order) != len(active_nodes):
        # cycle fallback: append remaining nodes in original position order
        remaining = sorted(
            (node for node in active_nodes if node not in order),
            key=lambda name: node_to_task[name].position,
        )
        order.extend(remaining)

    return order


def _compute_ancestors(parents_map: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    memo: Dict[str, Set[str]] = {}

    def visit(node: str) -> Set[str]:
        if node in memo:
            return memo[node]
        ancestors: Set[str] = set()
        for parent in parents_map.get(node, ()):
            ancestors.add(parent)
            ancestors.update(visit(parent))
        memo[node] = ancestors
        return ancestors

    for node in parents_map:
        visit(node)
    return memo


def _should_apply_gate(kind: str, gate: str) -> bool:
    scope = GATE_KIND_SCOPE.get(gate)
    if scope is None:
        return True
    kind_norm = (kind or "").upper()
    return kind_norm in scope


def _format_blockers(
    parents: Iterable[str],
    spec_blockers: Iterable[str],
    gates: Iterable[Tuple[str, str]],
) -> Tuple[str, str]:
    parent_list = sorted({p for p in parents if p})
    spec_list = sorted({p for p in spec_blockers if p})
    gate_list = sorted({g for g, _ in gates if g})
    gate_detail = {g: detail for g, detail in gates if g and detail}

    segments: List[str] = []
    reason_segments: List[str] = []

    if parent_list:
        joined = ",".join(parent_list)
        segments.append(f"parents={joined}")
        reason_segments.append(f"parents: {joined}")
    if spec_list:
        joined = ",".join(spec_list)
        segments.append(f"spec={joined}")
        reason_segments.append(f"spec ancestors: {joined}")
    if gate_list:
        joined = ",".join(gate_list)
        segments.append(f"requires={joined}")
        detail_parts = []
        for gate in gate_list:
            info = gate_detail.get(gate, "")
            if info:
                detail_parts.append(f"{gate} ({info})")
            else:
                detail_parts.append(gate)
        reason_segments.append("requires: " + ", ".join(detail_parts))

    if not segments:
        return "", ""

    status_value = f"{BLOCK_PREFIX}{';'.join(segments)})"
    reason_value = f"dag:auto {'; '.join(reason_segments)}".strip()
    return status_value, reason_value


def _update_task_status(
    cur: sqlite3.Cursor,
    task: TaskRecord,
    new_status: str,
    reason: str,
) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    assignments: Dict[str, Optional[str]] = {
        "status": new_status,
        "status_reason": reason or None,
        "updated_at": now,
        "last_run": RUN_STAMP,
    }

    if new_status == "pending":
        assignments["started_at"] = None
        assignments["completed_at"] = None
    elif new_status.startswith(BLOCK_PREFIX):
        if not task.started_at:
            assignments["started_at"] = now
        assignments["completed_at"] = None
    elif task.status_lower() not in DONE_STATUSES and new_status in DONE_STATUSES:
        if not task.started_at:
            assignments["started_at"] = now
        if not task.completed_at:
            assignments["completed_at"] = now

    set_clause = ", ".join(f"{column} = ?" for column in assignments.keys())
    params = list(assignments.values()) + [task.id]
    cur.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", params)

    # reflect updates locally
    task.status = new_status
    task.status_reason = reason or None
    if "started_at" in assignments:
        task.started_at = assignments["started_at"]
    if "completed_at" in assignments:
        task.completed_at = assignments["completed_at"]


def _evaluate_ready_gates(project_root: Path, gates: Sequence[str]) -> Dict[str, Tuple[bool, str]]:
    results: Dict[str, Tuple[bool, str]] = {}
    for gate in gates:
        key = gate.strip()
        if not key:
            continue
        if key == "no_rej":
            results[key] = _check_no_rej(project_root)
        elif key == "clean_tree":
            results[key] = _check_clean_tree(project_root)
        elif key == "schema_applied":
            results[key] = _check_schema_applied(project_root)
        elif key == "api_contract_exists":
            results[key] = _check_api_contract(project_root)
        else:
            results[key] = (True, "")
    return results


def _check_no_rej(project_root: Path) -> Tuple[bool, str]:
    for path in project_root.rglob("*.rej"):
        if path.is_file():
            rel = path.relative_to(project_root)
            return False, f"{rel}"
    return True, ""


def _check_clean_tree(project_root: Path) -> Tuple[bool, str]:
    git_dir = project_root / ".git"
    if not git_dir.exists():
        return True, ""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return True, ""
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if lines:
        return False, "; ".join(lines[:3])
    return True, ""


def _check_schema_applied(project_root: Path) -> Tuple[bool, str]:
    guard_script = project_root / "scripts" / "preflight_prisma_guard.sh"
    if guard_script.is_file():
        result = subprocess.run(
            ["bash", str(guard_script)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            # fall through to content probes to ensure lockout artifacts exist
            pass
        else:
            output = (result.stdout or result.stderr or "").strip()
            reason = output.splitlines()[0] if output else f"exit {result.returncode}"
            return False, reason

    schema_file = project_root / "prisma" / "schema.prisma"
    if not schema_file.is_file():
        return False, "schema.prisma missing"

    schema_dir = project_root / "prisma" / "migrations"
    if not schema_dir.is_dir():
        return False, "prisma migrations missing"

    keywords = ("login_attempt", "lockout", "unlock", "unlock_audit")
    for path in schema_dir.rglob("*.sql"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lowered = text.lower()
        if any(keyword in lowered for keyword in keywords):
            return True, ""

    return False, "lockout migration artifacts missing"


def _check_api_contract(project_root: Path) -> Tuple[bool, str]:
    candidates = [
        project_root / "openapi" / "admin.yaml",
        project_root / "openapi" / "admin.yml",
        project_root / "docs" / "openapi" / "admin.yaml",
    ]
    token = "POST /api/v1/admin/users/{userId}/unlock"
    contract_found = False
    for path in candidates:
        if not path.exists():
            continue
        try:
            if token.lower() in path.read_text(encoding="utf-8", errors="ignore").lower():
                contract_found = True
                break
        except Exception:
            continue
    if not contract_found:
        return False, "openapi unlock spec missing"

    handler_found = False
    handler_roots = [project_root / name for name in ("apps", "src", "services")]
    exts = {".ts", ".tsx", ".js", ".py", ".go"}
    for root in handler_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*unlock*"):
            if not path.is_file() or path.suffix.lower() not in exts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue
            if "unlock" in text and ("post" in text or "handler" in text or "controller" in text):
                handler_found = True
                break
        if handler_found:
            break

    if not handler_found:
        return False, "unlock handler missing"
    return True, ""


def _plan_story(
    project_root: Path,
    cur: sqlite3.Cursor,
    story_slug: str,
    story_id: str,
    dag: Optional[DagConfig],
    tasks: List[TaskRecord],
) -> Tuple[List[TaskRecord], Dict[str, Tuple[bool, str]]]:
    if not dag or not tasks:
        return tasks, {}

    node_to_task: Dict[str, TaskRecord] = {}
    task_to_node: Dict[int, str] = {}
    for task in tasks:
        node = _map_task_to_node(task, dag)
        if node and node not in node_to_task:
            node_to_task[node] = task
            task_to_node[task.id] = node

    children_map: Dict[str, Set[str]] = defaultdict(set)
    parents_map: Dict[str, Set[str]] = defaultdict(set)
    for src, dst in dag.edges:
        if src in dag.nodes and dst in dag.nodes:
            children_map[src].add(dst)
            parents_map[dst].add(src)

    topo_nodes = _topological_order(dag, node_to_task, children_map)
    ancestors_map = _compute_ancestors(parents_map)

    ordered_tasks: List[TaskRecord] = []
    seen_ids: Set[int] = set()

    for node in topo_nodes:
        task = node_to_task.get(node)
        if task and task.id not in seen_ids:
            ordered_tasks.append(task)
            seen_ids.add(task.id)

    for task in sorted(tasks, key=lambda t: t.position):
        if task.id not in seen_ids:
            ordered_tasks.append(task)
            seen_ids.add(task.id)

    gate_results = _evaluate_ready_gates(project_root, dag.ready_requires)

    for task in ordered_tasks:
        node = task_to_node.get(task.id)
        kind = ""
        if node:
            kind = dag.nodes.get(node, {}).get("kind", "")
        applicable_gates = [
            (gate, reason)
            for gate, (ok, reason) in gate_results.items()
            if not ok and _should_apply_gate(kind, gate)
        ]

        parent_blockers: Set[str] = set()
        spec_blockers: Set[str] = set()
        if node:
            for parent in parents_map.get(node, ()):
                parent_task = node_to_task.get(parent)
                if not parent_task:
                    parent_blockers.add(parent)
                    continue
                if parent_task.status_lower() not in DONE_STATUSES:
                    parent_blockers.add(parent)

            for ancestor in ancestors_map.get(node, ()):
                ancestor_task = node_to_task.get(ancestor)
                if not ancestor_task:
                    continue
                ancestor_kind = dag.nodes.get(ancestor, {}).get("kind", "")
                if ancestor_kind in {"ADR", "SPEC"} and ancestor_task.status_lower() not in DONE_STATUSES:
                    spec_blockers.add(ancestor)

        new_status, reason_text = _format_blockers(parent_blockers, spec_blockers, applicable_gates)

        current_is_blocked = task.status_lower().startswith(BLOCK_PREFIX)
        reason_is_dag = (task.status_reason or "").startswith("dag:auto")

        if new_status:
            if task.status != new_status or (task.status_reason or "") != reason_text:
                _update_task_status(cur, task, new_status, reason_text)
        elif current_is_blocked and reason_is_dag:
            _update_task_status(cur, task, "pending", "")

    return ordered_tasks, gate_results


def _resequence_tasks(cur: sqlite3.Cursor, tasks: List[TaskRecord]) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    temp_base = 1000
    for idx, task in enumerate(tasks):
        cur.execute(
            "UPDATE tasks SET position = ?, updated_at = ?, last_run = ? WHERE id = ?",
            (temp_base + idx, now, RUN_STAMP, task.id),
        )
    for idx, task in enumerate(tasks):
        cur.execute(
            "UPDATE tasks SET position = ?, updated_at = ?, last_run = ? WHERE id = ?",
            (idx, now, RUN_STAMP, task.id),
        )
        task.position = idx


def main() -> int:
    if len(sys.argv) < 4:
        return 1

    db_path = Path(sys.argv[1])
    story_filter_raw = (sys.argv[2] or "").strip().lower()
    resume_flag = sys.argv[3] == "1"

    project_root = Path(os.environ.get("PROJECT_ROOT") or os.getcwd()).resolve()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        stories = cur.execute(
            """
            SELECT story_slug, story_id, story_title, epic_key, epic_title, sequence, status
              FROM stories
             ORDER BY sequence ASC, story_slug ASC
            """
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return 0

    start_allowed = not story_filter_raw

    for story in stories:
        slug = str(story["story_slug"] or "")
        sequence = int(story["sequence"] or 0)
        story_id = str(story["story_id"] or "")
        epic_key = str(story["epic_key"] or "")
        epic_title = str(story["epic_title"] or "")
        story_title = str(story["story_title"] or "")
        story_status = str(story["status"] or "")

        slug_lower = slug.lower()

        if story_filter_raw and not start_allowed:
            keys = {
                story_id.strip().lower(),
                slug_lower,
                epic_key.strip().lower(),
                str(sequence),
            }
            if story_filter_raw in keys:
                start_allowed = True
            else:
                continue

        tasks = _fetch_story_tasks(cur, slug, story_id)
        dag = load_dag(project_root, slug) if slug else None
        tasks, gate_results = _plan_story(project_root, cur, slug, story_id, dag, tasks)

        if tasks:
            _resequence_tasks(cur, tasks)

        total = len(tasks)
        completed = sum(1 for task in tasks if task.status_lower() in DONE_STATUSES)
        next_index = 0

        if resume_flag:
            if not story_filter_raw and story_status.strip().lower() == "complete":
                conn.commit()
                continue
            for task in tasks:
                if task.status_lower() in DONE_STATUSES:
                    next_index = task.position + 1
                    continue
                next_index = task.position
                break
            else:
                next_index = total
        else:
            next_index = 0 if total > 0 else 0

        print(
            "\t".join(
                [
                    str(sequence),
                    slug,
                    story_id,
                    story_title.replace("\t", " ").replace("\n", " "),
                    epic_key.replace("\t", " ").replace("\n", " "),
                    epic_title.replace("\t", " ").replace("\n", " "),
                    str(total),
                    str(next_index),
                    str(completed),
                    story_status,
                ]
            )
        )

    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
