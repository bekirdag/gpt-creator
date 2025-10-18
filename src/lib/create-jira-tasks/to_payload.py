#!/usr/bin/env python3
"""Combine epics, stories, and tasks into the legacy tasks.json format."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".json")


def ensure_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value)
    return str(value).strip()


def section_block(heading: str, values: List[str]) -> str:
    if not values:
        return ""
    formatted = [f"- {v}" if not v.startswith("- ") else v for v in values]
    return f"\n{heading}:\n" + "\n".join(formatted)


def merge_description(base: Any, task: Dict[str, Any]) -> str:
    parts: List[str] = []
    base_text = coerce_str(base)
    if base_text:
        parts.append(base_text)

    mapping = [
        ("Endpoints", ensure_list(task.get("endpoints"))),
        ("Input contracts", ensure_list(task.get("data_contracts")) + ensure_list(task.get("inputs"))),
        ("Output contracts", ensure_list(task.get("outputs"))),
        ("Database", ensure_list(task.get("database"))),
        ("RBAC / Policy", ensure_list(task.get("rbac")) + ensure_list(task.get("policy")) + ensure_list(task.get("user_roles"))),
        ("Analytics & Observability", ensure_list(task.get("analytics")) + ensure_list(task.get("observability"))),
        ("QA notes", ensure_list(task.get("qa_notes")) + ensure_list(task.get("testing"))),
    ]
    for heading, values in mapping:
        block = section_block(heading, values)
        if block:
            parts.append(block)

    # Append sample payloads if provided
    sample_request = coerce_str(task.get("sample_request"))
    sample_response = coerce_str(task.get("sample_response"))
    if sample_request:
        parts.append("\nSample request JSON:\n" + sample_request)
    if sample_response:
        parts.append("\nSample response JSON:\n" + sample_response)

    return "\n".join(part.rstrip() for part in parts if part).strip()


def join_field(values: Any) -> Optional[str]:
    items = ensure_list(values)
    if not items:
        return None
    return "; ".join(items)


def normalize_status(value: Any) -> str:
    """Return a canonical status string or an empty string when unavailable."""
    status = coerce_str(value).lower()
    if not status:
        return ""
    status = status.replace("_", "-")
    synonyms = {
        "completed": "complete",
        "done": "complete",
        "finished": "complete",
        "complete": "complete",
        "in progress": "in-progress",
        "progress": "in-progress",
        "started": "in-progress",
        "on hold": "on-hold",
        "hold": "on-hold",
        "paused": "on-hold",
        "deferred": "on-hold",
        "waiting": "on-hold",
        "blocked": "blocked",
        "blocker": "blocked",
        "todo": "pending",
        "to-do": "pending",
        "backlog": "pending",
        "ready": "pending",
    }
    normalized = synonyms.get(status, status)
    allowed = {"pending", "in-progress", "complete", "blocked", "on-hold"}
    return normalized if normalized in allowed else ""


def load_tasks(
    epics_path: Path,
    stories_dir: Path,
    tasks_dir: Path,
    refined_dir: Path,
) -> List[Dict[str, Any]]:
    epics_data = read_json(epics_path)
    epic_lookup: Dict[str, Dict[str, Any]] = {}
    for epic in epics_data.get("epics", []):
        eid = coerce_str(epic.get("epic_id")).upper()
        if not eid:
            continue
        epic_lookup[eid] = epic

    story_lookup: Dict[str, Dict[str, Any]] = {}
    for story_file in list_files(stories_dir):
        payload = read_json(story_file)
        story = payload.get("story") or {}
        sid = coerce_str(story.get("story_id")).upper()
        if not sid:
            continue
        story_lookup[sid] = {
            "epic_id": coerce_str(payload.get("epic_id")).upper(),
            "story": story,
            "slug": story_file.stem,
        }

    tasks_payload: List[Dict[str, Any]] = []

    for sid, info in story_lookup.items():
        epic_id = info.get("epic_id", "")
        story_data = info.get("story", {})
        story_title = coerce_str(story_data.get("title")) or coerce_str(story_data.get("name"))
        story_slug = info.get("slug")
        base_tasks_path = tasks_dir / f"{story_slug}.json"
        if not base_tasks_path.exists():
            continue
        tasks_raw = read_json(base_tasks_path)
        refined_path = refined_dir / f"{story_slug}.json"
        if refined_path.exists():
            tasks_raw = read_json(refined_path)

        story_id = coerce_str(tasks_raw.get("story_id") or sid).upper()
        story_title = coerce_str(tasks_raw.get("story_title")) or story_title

        task_entries = tasks_raw.get("tasks") or []
        for pos, task in enumerate(task_entries):
            task_id = coerce_str(task.get("id") or task.get("task_id") or f"{story_id}-T{pos+1:02d}").upper()
            title = coerce_str(task.get("title")) or "Untitled task"
            description = merge_description(task.get("description"), task)

            acceptance = ensure_list(task.get("acceptance_criteria"))
            dependencies = ensure_list(task.get("dependencies"))
            tags = ensure_list(task.get("tags"))
            assignees = ensure_list(task.get("assignees"))
            story_points = coerce_str(task.get("story_points") or task.get("estimate"))
            estimate = coerce_str(task.get("estimate")) or story_points
            status = (
                normalize_status(
                    task.get("status")
                    or task.get("state")
                    or task.get("progress")
                    or task.get("task_status")
                )
            )

            payload = {
                "epic_id": epic_id,
                "epic_title": coerce_str(epic_lookup.get(epic_id, {}).get("title")),
                "story_id": story_id,
                "story_title": story_title,
                "id": task_id,
                "title": title,
                "description": description,
                "acceptance_criteria": acceptance,
                "dependencies": dependencies,
                "tags": tags,
                "assignees": assignees,
                "estimate": estimate,
                "story_points": story_points,
                "document_reference": join_field(task.get("document_references") or task.get("document_reference")),
                "endpoints": join_field(task.get("endpoints")),
                "qa_notes": join_field(task.get("qa_notes")),
                "rbac": join_field(task.get("rbac") or task.get("policy")),
                "observability": join_field(task.get("observability")),
                "performance_targets": join_field(task.get("performance")),
                "messaging_workflows": join_field(task.get("messaging")),
                "user_story_ref_id": coerce_str(task.get("user_story_ref_id")),
                "epic_ref_id": coerce_str(task.get("epic_ref_id")),
                "sample_create_request": coerce_str(task.get("sample_request")),
                "sample_create_response": coerce_str(task.get("sample_response")),
            }

            # Derived text fields for legacy compatibility
            payload["tags_text"] = join_field(tags)
            payload["assignee_text"] = join_field(assignees)
            payload["dependencies_text"] = join_field(dependencies)
            if status:
                payload["status"] = status

            tasks_payload.append(payload)

    return tasks_payload


def main() -> None:
    if len(sys.argv) != 6:
        raise SystemExit(
            "Usage: to_payload.py <epics.json> <stories_dir> <tasks_dir> <refined_dir> <output.json>"
        )

    epics_path = Path(sys.argv[1])
    stories_dir = Path(sys.argv[2])
    tasks_dir = Path(sys.argv[3])
    refined_dir = Path(sys.argv[4])
    output_path = Path(sys.argv[5])

    tasks_payload = load_tasks(epics_path, stories_dir, tasks_dir, refined_dir)
    output_path.write_text(json.dumps({"tasks": tasks_payload}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
