#!/usr/bin/env python3
"""Render the story prompt for a given epic using staged context."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "system",
    "user",
    "story",
    "should",
    "will",
    "must",
    "allow",
    "support",
    "able",
    "data",
    "api",
    "admin",
    "project",
    "documentation",
    "context",
    "section",
}
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_\/]{2,}")


def parse_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


SECTION_LIMIT = parse_int("CJT_STORY_CONTEXT_SECTION_LIMIT", 6)
SNIPPET_CHAR_LIMIT = parse_int("CJT_STORY_CONTEXT_SECTION_CHAR_LIMIT", 1200)
TOTAL_CHAR_LIMIT = parse_int("CJT_STORY_CONTEXT_TOTAL_CHAR_LIMIT", 5500)


def load_sections(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8", errors="ignore")
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("## "):
            if current_title is not None and current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip() or "Section"
            current_lines = []
            continue
        if line.startswith("# "):
            continue
        if current_title is None:
            continue
        current_lines.append(line)
    if current_title is not None and current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections


def extract_keywords(epic_payload: dict) -> set[str]:
    tokens: list[str] = []
    for key in ("title", "summary"):
        value = epic_payload.get(key)
        if isinstance(value, str):
            tokens.append(value)
    for key in ("acceptance_criteria", "primary_roles", "dependencies"):
        value = epic_payload.get(key)
        if isinstance(value, list):
            tokens.extend(str(item) for item in value if item)
    blob = " ".join(tokens).lower()
    keywords = {token.strip("-_/") for token in TOKEN_RE.findall(blob) if len(token) > 3}
    return {kw for kw in keywords if kw and kw not in STOPWORDS}


def score_sections(sections: list[tuple[str, str]], keywords: set[str]) -> list[tuple[int, int, int, str, str]]:
    scored: list[tuple[int, int, int, str, str]] = []
    for idx, (title, body) in enumerate(sections):
        title_lower = title.lower()
        if title_lower.startswith("documentation library") or title_lower.startswith("documentation table of contents"):
            continue
        lower = body.lower()
        score = sum(lower.count(keyword) for keyword in keywords)
        length_score = min(len(body), 2000)
        scored.append((score, length_score, idx, title, body))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return scored


def select_sections(sections: list[tuple[str, str]], keywords: set[str]) -> list[tuple[str, str]]:
    scored = score_sections(sections, keywords)
    if not scored:
        return []
    remaining = len(scored) if SECTION_LIMIT <= 0 else min(SECTION_LIMIT, len(scored))
    total_chars = 0
    selected: list[tuple[str, str]] = []
    for score, length_score, idx, title, body in scored:
        if remaining == 0:
            break
        snippet = body
        if SNIPPET_CHAR_LIMIT > 0 and len(snippet) > SNIPPET_CHAR_LIMIT:
            snippet = snippet[:SNIPPET_CHAR_LIMIT].rstrip()
            snippet += "\n... (truncated; see consolidated context for full details)"
        snippet_len = len(snippet)
        if TOTAL_CHAR_LIMIT > 0 and total_chars + snippet_len > TOTAL_CHAR_LIMIT:
            allowance = TOTAL_CHAR_LIMIT - total_chars
            if allowance <= 0:
                break
            snippet = snippet[:allowance].rstrip()
            if snippet:
                snippet += "\n... (truncated; see consolidated context for full details)"
                snippet_len = len(snippet)
            else:
                break
        selected.append((title, snippet))
        total_chars += snippet_len
        remaining -= 1
    if not selected and scored:
        fallback = scored[0][3], scored[0][4]
        return [fallback]
    return selected


def write_story_prompt(
    epics_path: Path,
    epic_id: str,
    prompt_path: Path,
    context_path: Path,
    project_label: str,
) -> None:
    data = json.loads(epics_path.read_text(encoding="utf-8"))
    match = None
    for epic in data.get("epics", []):
        if str(epic.get("epic_id")).strip().lower() == epic_id.lower():
            match = epic
            break

    if not match:
        raise SystemExit(f"Epic {epic_id} not found in epics.json")

    sections = load_sections(context_path)
    keywords = extract_keywords(match)
    selected_sections = select_sections(sections, keywords)

    with prompt_path.open("w", encoding="utf-8") as fh:
        fh.write(
            f"You are a lead product analyst expanding Jira epics into granular user stories for the {project_label} initiative.\n\n"
        )
        fh.write("Only focus on the website and admin/backoffice surfaces. Ignore DevOps/infra.\n\n")
        fh.write("## Target epic\n")
        json.dump(match, fh, indent=2)
        fh.write("\n\n")
        fh.write("## Focused documentation excerpts\n")
        if selected_sections:
            for title, snippet in selected_sections:
                fh.write(f"### {title}\n")
                fh.write(snippet)
                if not snippet.endswith("\n"):
                    fh.write("\n")
                fh.write("\n")
        else:
            fh.write("(No high-confidence documentation sections matched; consult the consolidated context if needed.)\n\n")
        fh.write("## Requirements\n")
        fh.write(
            "- Produce exhaustive user stories that cover sunny-day flows, edge cases, validation errors, state transitions, and accessibility requirements for this epic.\n"
        )
        fh.write("- Use identifiers following the pattern '<epic-id>-US-XX'. Start numbering at 01.\n")
        fh.write("- Provide a user story narrative (role, goal, benefit) and detailed description of scope.\n")
        fh.write("- List acceptance criteria as bullet-equivalent strings (cover positive and negative cases).\n")
        fh.write("- Note any dependencies on other epics/stories when relevant.\n")
        fh.write("- Tag each story with domains (e.g., Web-FE, Web-BE, Admin-FE, Admin-BE).\n")
        fh.write("- Capture primary user roles touched by the story.\n\n")
        fh.write("## Output (JSON only)\n")
        fh.write(
            "{\n"
            f'  "epic_id": "{epic_id}",\n'
            '  "user_stories": [\n'
            "    {\n"
            f'      "story_id": "{epic_id}-US-01",\n'
            '      "title": "",\n'
            '      "narrative": "As a <role> I want ... so that ...",\n'
            '      "description": "Detailed scope and notes...",\n'
            '      "acceptance_criteria": ["..."],\n'
            '      "tags": ["Web-FE"],\n'
            '      "dependencies": ["WEB-02-US-02"],\n'
            '      "user_roles": ["Visitor"],\n'
            '      "non_functional": ["WCAG 2.2 AA"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )
        fh.write("\nReturn strictly valid JSON without fences or extra commentary.\n")


def main() -> int:
    if len(sys.argv) < 5:
        return 1
    epics_path = Path(sys.argv[1])
    epic_id = sys.argv[2]
    prompt_path = Path(sys.argv[3])
    context_path = Path(sys.argv[4])
    project_label = os.environ.get("CJT_PROMPT_TITLE", "the product").strip() or "the product"
    write_story_prompt(epics_path, epic_id, prompt_path, context_path, project_label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
