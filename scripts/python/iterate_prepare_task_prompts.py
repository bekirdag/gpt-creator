#!/usr/bin/env python3
"""Generate per-task Codex prompts for `gpt-creator iterate`."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def build_lines(index: int, task: dict[str, object], project_root: str) -> list[str]:
    title = (task.get("title") or "").strip() or f"Task {index}"
    task_id = (task.get("id") or "").strip()
    description = (task.get("description") or "").strip() or "(No additional details provided.)"
    estimate = (task.get("estimate") or "").strip()
    tags = ", ".join(task.get("tags") or [])
    assignees = ", ".join(task.get("assignees") or [])
    story_bits = [
        part for part in [(task.get("story_id") or "").strip(), (task.get("story_title") or "").strip()] if part
    ]

    header = f"# Task {index}: {task_id} — {title}" if task_id and not title.startswith(task_id) else f"# Task {index}: {title}"

    lines = [header, "", "## Context", f"- Working directory: {project_root}"]
    if task_id:
        lines.append(f"- Task ID: {task_id}")
    if story_bits:
        lines.append(f"- Story: {' — '.join(story_bits)}")
    if assignees:
        lines.append(f"- Assignees: {assignees}")
    if estimate:
        lines.append(f"- Estimate: {estimate}")
    if tags:
        lines.append(f"- Tags: {tags}")

    lines.extend(
        [
            "",
            "## Description",
            description or "(No additional details provided.)",
            "",
        ]
    )

    acceptance = task.get("acceptance_criteria") or []
    if acceptance:
        lines.append("## Acceptance Criteria")
        for ac in acceptance:
            lines.append(f"- {ac}")
        lines.append("")

    dependencies = task.get("dependencies") or []
    if dependencies:
        lines.append("## Dependencies")
        for dep in dependencies:
            lines.append(f"- {dep}")
        lines.append("")

    lines.extend(
        [
            "",
            "## Instructions",
            "- Outline your plan before modifying files.",
            "- Implement the task in the repository; commits are not required.",
            "- Show relevant diffs (git snippets) and command results.",
            "- Verify acceptance criteria for this task.",
            "- If blocked, explain why and propose next steps.",
            "",
            "## Output Format",
            f"- Begin with a heading `Task {index}`.",
            "- Summarise changes, tests, and outstanding follow-ups.",
        ]
    )
    return lines


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(1)

    source = Path(sys.argv[1])
    out_dir = Path(sys.argv[2])
    project_root = sys.argv[3]

    data = json.loads(source.read_text(encoding="utf-8"))
    tasks = data.get("tasks", []) if isinstance(data, dict) else []

    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "tasks-order.txt"

    with index_path.open("w", encoding="utf-8") as idx:
        for i, task in enumerate(tasks, 1):
            prompt_path = out_dir / f"task-{i:02d}.md"
            idx.write(f"{prompt_path}\n")
            lines = build_lines(i, task, project_root)
            prompt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
