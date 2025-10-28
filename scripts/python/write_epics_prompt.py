#!/usr/bin/env python3
"""Render the epics prompt using staged context files."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROMPT_BODY = """## Requirements
- Create a comprehensive backlog of Jira epics that covers every piece of functionality the website and admin/backoffice must deliver.
- Use identifiers `WEB-XX` for website-facing epics and `ADM-XX` for admin/backoffice epics. Start numbering at 01.
- Ensure the epics collectively span navigation, authentication, content, commerce/workflows, reporting, localization, accessibility, error states, and any other requirements found in the docs.
- Provide rich acceptance criteria per epic describing what success looks like (include non-functional needs such as performance, security, accessibility when applicable).
- Note any cross-epic dependencies.
- Include a short call-out of the primary user roles touched by the epic.

## Output format (JSON only)
{{
  "epics": [
    {{
      "epic_id": "WEB-01",
      "title": "Global shell, navigation, and layout",
      "summary": "High-level objective for the epic",
      "acceptance_criteria": ["Clear measurable criteria ..."],
      "dependencies": ["ADM-02"],
      "primary_roles": ["Visitor", "Member", "Admin"],
      "scope": "web"
    }}
  ]
}}

Return strictly valid JSON; do not include markdown fences or commentary.
"""


def strip_ansi(text: str) -> str:
    import re

    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_re.sub("", text)


def load_context(primary: Path, fallback: Path) -> str:
    if primary.exists() and primary.stat().st_size > 0:
        content = primary.read_text(encoding="utf-8", errors="ignore")
    else:
        content = fallback.read_text(encoding="utf-8", errors="ignore")
    return strip_ansi(content)


def write_epics_prompt(prompt_path: Path, project_label: str, epic_context: Path, snippet_context: Path) -> None:
    context_excerpt = load_context(epic_context, snippet_context)
    with prompt_path.open("w", encoding="utf-8") as handle:
        handle.write(
            f"You are a senior delivery lead creating Jira epics for the {project_label} initiative.\n\n"
        )
        handle.write(
            "Project scope: prioritize the customer-facing and admin/backoffice experiences described in the documentation.\n"
        )
        handle.write("Ignore DevOps, infrastructure, and tooling work unless explicitly documented.\n")
        handle.write(
            "Review the documentation catalog, table of contents, and excerpts below before proposing epics. "
            "Reuse doc IDs/headings to stay grounded in the staged sources.\n\n"
        )
        handle.write("## Context Excerpt (summary)\n")
        handle.write(context_excerpt.rstrip() + "\n\n")
        handle.write(PROMPT_BODY)


def main() -> int:
    if len(sys.argv) < 4:
        return 1
    prompt_file = Path(sys.argv[1])
    epic_context_path = Path(sys.argv[2])
    snippet_context_path = Path(sys.argv[3])
    project_label = os.environ.get("CJT_PROJECT_TITLE", "this project").strip() or "this project"
    write_epics_prompt(prompt_file, project_label, epic_context_path, snippet_context_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
