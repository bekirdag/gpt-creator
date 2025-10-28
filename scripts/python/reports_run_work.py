#!/usr/bin/env python3
"""Generate a Codex work prompt from a report YAML entry."""

from __future__ import annotations

import sys
from pathlib import Path


def load_report(path: Path) -> tuple[str, str, str, dict[str, str]]:
    raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    summary = ""
    priority = ""
    definition_lines: list[str] = []
    metadata: dict[str, str] = {}
    collect_definition = False
    metadata_active = False

    for line in raw_lines:
        if line.startswith("summary:") and not summary:
            value = line.split(":", 1)[1].strip()
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
            summary = value
        elif line.startswith("priority:") and not priority:
            priority = line.split(":", 1)[1].strip()
        elif line.startswith("issue_definition:"):
            collect_definition = True
            continue
        elif collect_definition:
            if line.startswith("  "):
                definition_lines.append(line[2:])
            else:
                collect_definition = False
        if line.strip() == "metadata:":
            metadata_active = True
            continue
        if metadata_active:
            if line.startswith("  "):
                stripped = line.strip()
                if ":" in stripped:
                    k, v = stripped.split(":", 1)
                    metadata[k.strip()] = v.strip().strip('"')
            else:
                metadata_active = False

    definition_text = "\n".join(definition_lines).strip()
    return summary, priority, definition_text, metadata


def build_prompt(
    *,
    report_path: Path,
    prompt_path: Path,
    project_root: Path,
    slug: str,
    branch: str,
    push: bool,
) -> None:
    summary, priority, definition_text, metadata = load_report(report_path)

    issue_type = metadata.get("type", "unknown")
    status = metadata.get("status", "open")
    timestamp = metadata.get("timestamp", "")
    likes = metadata.get("likes", "0")
    comments = metadata.get("comments", "0")
    try:
        popularity = int(likes) + int(comments)
    except ValueError:
        popularity = 0

    summary_for_commit = summary.replace('"', "").strip()
    if len(summary_for_commit) > 64:
        summary_for_commit = summary_for_commit[:61] + "..."

    instructions: list[str] = []
    instructions.append(f"# Resolve Issue {slug}\n")
    instructions.append("## Summary")
    instructions.append(f"- Summary: {summary or '(not provided)'}")
    instructions.append(f"- Priority: {priority or 'unknown'}")
    instructions.append(f"- Type: {issue_type}")
    instructions.append(f"- Current Status: {status}")
    instructions.append(f"- Popularity Score: {popularity} (likes={likes}, comments={comments})")
    if timestamp:
        instructions.append(f"- Reported At: {timestamp}")
    instructions.append(f"- Report File: {report_path}")
    instructions.append(f"- Working Branch: {branch}")
    instructions.append("")
    instructions.append("## Issue Definition")
    instructions.append("```")
    instructions.append(definition_text or "(no issue definition provided)")
    instructions.append("```")
    instructions.append("")
    instructions.append("## Workflow Requirements")
    instructions.append(f"1. Checkout the branch `{branch}` (create it if missing).")
    instructions.append("2. Investigate and resolve the described issue with deterministic steps.")
    instructions.append(
        "3. Run any relevant checks or tests (e.g. `gpt-creator verify acceptance`) to confirm the fix."
    )
    instructions.append(
        f"4. Stage and commit the changes with a concise message "
        f"(suggested: `fix: {slug} {summary_for_commit}`)."
    )
    if push:
        instructions.append(f"5. Push the branch to origin via `git push origin {branch}`.")
    instructions.append(
        "6. Provide a short summary of the fix in the commit message body if additional context is required."
    )
    instructions.append("")
    instructions.append("## Notes for Codex")
    instructions.append("- Operate deterministically and avoid modifying unrelated files.")
    instructions.append("- Do not edit the issue report YAML; the CLI updates metadata automatically.")
    instructions.append("- Focus on resolving the root cause and keep diffs as small as possible.")
    instructions.append(
        "- If the issue cannot be resolved, leave the repository unchanged and exit with a failure code describing the blocker."
    )
    instructions.append("")
    instructions.append("## Repository Context")
    instructions.append(f"- Project Root: {project_root}")
    instructions.append(f"- Branch: {branch}")
    instructions.append("")

    prompt_path.write_text("\n".join(instructions).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit(
            "usage: reports_run_work.py <report_path> <prompt_path> <project_root> <slug> <branch> <push_flag>"
        )
    report_path = Path(sys.argv[1])
    prompt_path = Path(sys.argv[2])
    project_root = Path(sys.argv[3])
    slug = sys.argv[4]
    branch = sys.argv[5]
    push_flag = sys.argv[6] == "1"

    build_prompt(
        report_path=report_path,
        prompt_path=prompt_path,
        project_root=project_root,
        slug=slug,
        branch=branch,
        push=push_flag,
    )


if __name__ == "__main__":
    main()

