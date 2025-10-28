#!/usr/bin/env python3
"""Build Codex summary prompt after iterate task runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(1)

    tasks_path = Path(sys.argv[1])
    order_file = Path(sys.argv[2])
    prompt_path = Path(sys.argv[3])

    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", []) if isinstance(data, dict) else []

    lines: list[str] = [
        "# Summary Request",
        "",
        "Summarise the completed Jira work and list follow-up actions.",
        "",
        "## Task Reports",
    ]

    if order_file.exists():
        prompts = [line for line in order_file.read_text(encoding="utf-8").splitlines() if line]
        for i, prompt in enumerate(prompts, 1):
            title = tasks[i - 1].get("title") if i - 1 < len(tasks) else f"Task {i}"
            lines.append(f"- Task {i}: {title}")
            out_path = Path(prompt).with_suffix(".output.md")
            if out_path.exists():
                content = out_path.read_text(encoding="utf-8").strip()
                if content:
                    snippet = content[:2000]
                    lines.append("  ```")
                    lines.append(snippet)
                    lines.append("  ```")
            else:
                lines.append("  (No output captured)")
    else:
        lines.append("- No outputs available.")

    lines.extend(
        [
            "",
            "## Output Requirements",
            "- Provide an overall summary of work completed.",
            "- List follow-up items or blockers.",
            "- Use markdown headings and bullet lists.",
        ]
    )

    prompt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
