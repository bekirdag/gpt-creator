#!/usr/bin/env python3
"""Render the task prompt for a given story using staged context and SDS chunks."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple


def extract_keywords(story_data: dict) -> set[str]:
    fields: List[str] = []
    for key in ("title", "narrative", "description"):
        value = story_data.get(key) or ""
        if isinstance(value, str):
            fields.append(value)
    extra = story_data.get("acceptance_criteria")
    if isinstance(extra, list):
        fields.extend(str(item) for item in extra if item)
    joined = " ".join(fields).lower()
    raw_tokens = re.findall(r"[a-z0-9][a-z0-9\-_\/]{2,}", joined)
    stopwords = {
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
    }
    keywords = {token.strip("-_/") for token in raw_tokens if len(token) > 3}
    return {kw for kw in keywords if kw and kw not in stopwords}


def score_text(text: str, keywords: set[str]) -> int:
    if not text:
        return 0
    lower = text.lower()
    return sum(lower.count(keyword) for keyword in keywords)


def summarize_text(text: str, char_limit: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if char_limit > 0 and len(text) > char_limit:
        trimmed = text[:char_limit].rstrip()
        return f"{trimmed}\n... (truncated; consult source for full details)"
    return text


def single_line_summary(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return ""
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "…"
    return text


def parse_context_sections(blob: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = "Overview"
    current_lines: list[str] = []
    for line in blob.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip() or "Section"
            current_lines = []
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    deduped: list[tuple[str, str]] = []
    seen = set()
    for title, text in sections:
        key = (title, text[:200])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((title, text))
    return deduped


def choose_context_sections(blob: str, keywords: set[str]) -> list[tuple[str, str]]:
    max_sections = int(os.environ.get("CJT_TASK_CONTEXT_SECTION_LIMIT", "3"))
    char_limit = int(os.environ.get("CJT_TASK_CONTEXT_SECTION_CHAR_LIMIT", "450"))
    summary_limit = int(os.environ.get("CJT_TASK_CONTEXT_SUMMARY_CHAR_LIMIT", "220"))
    sections = parse_context_sections(blob)
    filtered_sections: list[tuple[str, str]] = []
    scored: list[tuple[int, str, str]] = []
    for title, text in sections:
        snippet = summarize_text(text, char_limit)
        if not snippet:
            continue
        summary = single_line_summary(snippet, summary_limit)
        score = score_text(text, keywords)
        scored.append((score, title, summary))
    scored.sort(key=lambda item: item[0], reverse=True)
    filtered = [entry for entry in scored if entry[0] > 0][:max_sections]
    if not filtered:
        filtered = scored[:max_sections]
    return [(title, summary) for _, title, summary in filtered if summary]


def load_sds_chunks(list_path: Path) -> list[tuple[str, str, str, str]]:
    entries: list[tuple[str, str, str, str]] = []
    for line in list_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 2)
        chunk_path = Path(parts[0].strip())
        label = parts[1].strip() if len(parts) > 1 else ""
        heading = parts[2].strip() if len(parts) > 2 else ""
        if not chunk_path.exists():
            continue
        try:
            content = chunk_path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if content:
            entries.append((chunk_path.name, label, heading, content))
    return entries


def choose_sds_chunks(
    entries: list[tuple[str, str, str, str]], keywords: set[str]
) -> tuple[list[str], list[tuple[str, str]], int]:
    if not entries:
        return [], [], 0
    overview_limit = int(os.environ.get("CJT_TASK_SDS_OVERVIEW_LIMIT", "4"))
    chunk_limit = int(os.environ.get("CJT_TASK_SDS_CHUNK_LIMIT", "3"))
    snippet_char_limit = int(os.environ.get("CJT_TASK_SDS_SNIPPET_CHAR_LIMIT", "400"))
    summary_limit = int(os.environ.get("CJT_TASK_SDS_SUMMARY_CHAR_LIMIT", "200"))
    scored: list[tuple[int, str, str, str, str]] = []
    for name, label, heading, content in entries:
        meta = " ".join(filter(None, (name, label, heading)))
        combined = f"{meta}\n{content}"
        score = score_text(combined, keywords)
        scored.append((score, name, label, heading, content))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [entry for entry in scored if entry[0] > 0][:chunk_limit]
    if not selected:
        selected = scored[:chunk_limit]
    overview_entries = selected[:overview_limit]
    prepared: list[tuple[str, str]] = []
    for _, name, label, heading, content in selected:
        ref = f"SDS {label}" if label else (heading or name)
        summary_text = summarize_text(content, snippet_char_limit)
        summary = single_line_summary(summary_text, summary_limit)
        prepared.append((ref, summary))
    overview_list: list[str] = []
    for _, name, label, heading, _ in overview_entries:
        ref = f"SDS {label}" if label else (heading or name)
        overview_list.append(ref)
    omitted_total = max(0, len(entries) - len(selected))
    return overview_list, prepared, omitted_total


def write_task_prompt(
    story_path: Path,
    context_path: Path,
    prompt_path: Path,
    sds_chunk_list: Path | None,
) -> None:
    story_payload = json.loads(story_path.read_text(encoding="utf-8"))
    epic_id = story_payload.get("epic_id")
    story = story_payload.get("story")
    if not story:
        raise SystemExit(f"Story payload missing in {story_path}")

    context_raw = context_path.read_text(encoding="utf-8")
    story_keywords = extract_keywords(story)
    context_refs = choose_context_sections(context_raw, story_keywords)

    sds_refs: list[tuple[str, str]] = []
    sds_omitted = 0
    if sds_chunk_list and sds_chunk_list.exists():
        sds_entries = load_sds_chunks(sds_chunk_list)
        if sds_entries:
            _, sds_refs, sds_omitted = choose_sds_chunks(sds_entries, story_keywords)

    with prompt_path.open("w", encoding="utf-8") as fh:
        fh.write("You are a delivery engineer decomposing a single user story into actionable Jira tasks.\n\n")
        fh.write("Consider frontend, backend, admin UI, data, security, accessibility, analytics, and QA needs.\n\n")
        fh.write("## User story\n")
        json.dump(story, fh, indent=2)
        fh.write("\n\n")
        fh.write("## Epic context\n")
        json.dump({"epic_id": epic_id}, fh, indent=2)
        fh.write("\n\n")
        fh.write("## Focused documentation references\n")
        if context_refs:
            for title, summary in context_refs:
                fh.write(f"- {title}: {summary}\n")
            fh.write("\n")
        else:
            fh.write("(No high-confidence documentation sections matched; consult the consolidated context if needed.)\n\n")
        fh.write("## Requirements\n")
        fh.write("- Cover happy paths, error handling, analytics, and release readiness considerations.\n")
        fh.write("- Assign owners, note dependencies, and tag each task for the impacted surfaces (Web-FE, API, DB, QA, etc.).\n")
        fh.write("- Provide numeric story points and hour estimates consistent with the workload.\n")
        fh.write("- Reference documentation by identifier (e.g., SDS §10.1.1, SQL:users, API:/v1/auth) instead of pasting content.\n")
        fh.write("- Describe APIs, data contracts, validations, and required testing (unit, integration, E2E).\n\n")
        if sds_refs:
            fh.write("## SDS references\n")
            for ref, summary in sds_refs:
                if summary:
                    fh.write(f"- {ref}: {summary}\n")
                else:
                    fh.write(f"- {ref}\n")
            if sds_omitted > 0:
                fh.write(f"- ...(additional {sds_omitted} sections omitted; see full SDS for details)\n")
            fh.write("\n")
        fh.write("## Output JSON schema\n")
        fh.write(
            "{\n"
            '  "story_id": "...",\n'
            '  "story_title": "...",\n'
            '  "tasks": [\n'
            "    {\n"
            '      "id": "WEB-01-T01",\n'
            '      "title": "...",\n'
            '      "description": "Detailed instructions...",\n'
            '      "acceptance_criteria": ["..."],\n'
            '      "tags": ["Web-FE"],\n'
            '      "assignees": ["FE dev"],\n'
            '      "estimate": 5,\n'
            '      "story_points": 5,\n'
            '      "dependencies": ["WEB-01-T00"],\n'
            '      "document_references": ["SDS §10.1.1"],\n'
            '      "endpoints": ["GET /api/v1/..."],\n'
            '      "data_contracts": ["Request payloads, DB tables, indexes, policies, RBAC"],\n'
            '      "qa_notes": ["Unit tests, integration tests"],\n'
            '      "user_roles": ["Visitor"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )
        fh.write("Return strictly valid JSON with all required fields.\n")


def main() -> int:
    if len(sys.argv) < 4:
        return 1
    story_file = Path(sys.argv[1])
    context_snippet = Path(sys.argv[2])
    prompt_file = Path(sys.argv[3])
    sds_chunk_list = Path(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None
    write_task_prompt(story_file, context_snippet, prompt_file, sds_chunk_list)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
