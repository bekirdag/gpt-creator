#!/usr/bin/env python3
"""Render the epics prompt using staged context files."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROMPT_BODY = """## Requirements
- Create a comprehensive backlog of Jira epics that matches the documented scope. Only include surfaces explicitly requested (e.g., CLI/daemon, library, API, web, admin, mobile). Do not add mobile/admin/web/API/db work unless the docs require it.
- Use identifiers that fit the project (reuse any scheme from the docs; otherwise use `EP-XX`). Start numbering at 01 per scheme.
- Ensure epics cover the functional themes, non-functional constraints, and integrations mentioned in the docs. Skip infra/DevOps/telemetry unless explicitly documented.
- Provide concise acceptance criteria per epic describing what success looks like. When a concern (performance, security, accessibility, localization) is not mentioned, omit it rather than guessing.
- Note any cross-epic dependencies and primary user roles.

## Output format (JSON only)
{{
  "epics": [
    {{
      "epic_id": "EP-01",
      "title": "Primary objective",
      "summary": "High-level objective for the epic",
      "acceptance_criteria": ["Clear measurable criteria ..."],
      "dependencies": ["ADM-02"],
      "primary_roles": ["Visitor", "Member", "Admin"],
      "scope": "api"
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
            "Project scope: use only what is documented; do not invent additional surfaces or technologies.\n"
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
