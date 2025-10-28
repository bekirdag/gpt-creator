#!/usr/bin/env python3
"""Render inline refinement prompt for a single task."""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

tasks_path = Path(sys.argv[1])
task_index = int(sys.argv[2])
context_path = Path(sys.argv[3])
prompt_path = Path(sys.argv[4])
sds_list_path = Path(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] else None
pdr_path = Path(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] else None
sql_path = Path(sys.argv[7]) if len(sys.argv) > 7 and sys.argv[7] else None
db_path = Path(sys.argv[8]) if len(sys.argv) > 8 and sys.argv[8] else None
project_base = os.environ.get("CJT_PROMPT_TITLE", "the project").strip() or "the project"
project_label = f"{project_base} delivery team"

CONTEXT_SECTION_LIMIT = int(os.environ.get("CJT_REFINE_CONTEXT_SECTION_LIMIT", "2"))
CONTEXT_SECTION_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_CONTEXT_SECTION_CHAR_LIMIT", "320"))
CONTEXT_SECTION_SUMMARY_LIMIT = int(os.environ.get("CJT_REFINE_CONTEXT_SUMMARY_CHAR_LIMIT", "180"))
PDR_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_PDR_CHAR_LIMIT", "360"))
SQL_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_SQL_CHAR_LIMIT", "360"))
SDS_OVERVIEW_LIMIT = int(os.environ.get("CJT_REFINE_SDS_OVERVIEW_LIMIT", "3"))
SDS_CHUNK_LIMIT = int(os.environ.get("CJT_REFINE_SDS_CHUNK_LIMIT", "2"))
SDS_SNIPPET_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_SDS_SNIPPET_CHAR_LIMIT", "220"))
SDS_SNIPPET_SUMMARY_LIMIT = int(os.environ.get("CJT_REFINE_SDS_SUMMARY_CHAR_LIMIT", "180"))
OTHER_TASKS_LIMIT = int(os.environ.get("CJT_REFINE_OTHER_TASKS_LIMIT", "3"))
OTHER_TASKS_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_OTHER_TASKS_CHAR_LIMIT", "110"))
TASK_FIELD_CHAR_LIMIT = int(os.environ.get("CJT_REFINE_TASK_FIELD_CHAR_LIMIT", "220"))
TASK_FIELD_LIST_LIMIT = int(os.environ.get("CJT_REFINE_TASK_LIST_LIMIT", "3"))

payload = json.loads(tasks_path.read_text(encoding="utf-8"))
tasks = payload.get("tasks") or []
if task_index < 0 or task_index >= len(tasks):
    raise SystemExit(f"Task index {task_index} out of range for {tasks_path}")

target_task = tasks[task_index]
story = payload.get("story") or {}
epic_id = payload.get("epic_id") or story.get("epic_id") or ""
epic_title = payload.get("epic_title") or story.get("epic_title") or ""
story_id = payload.get("story_id") or story.get("story_id") or ""
story_title = payload.get("story_title") or story.get("title") or ""
story_description = story.get("description") or payload.get("story_description") or ""
story_roles = story.get("user_roles") or payload.get("story_roles") or []
story_acceptance = story.get("acceptance_criteria") or payload.get("story_acceptance_criteria") or []
story_slug = payload.get("story_slug") or tasks_path.stem

context_blob = ""
if context_path.exists():
    context_blob = context_path.read_text(encoding="utf-8", errors="ignore")

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "system", "user", "story",
    "should", "will", "must", "allow", "support", "able", "data", "api", "admin",
    "task", "jira"
}

REQUIRED_TEXT_FIELDS = ("title", "description")
REQUIRED_LIST_FIELDS = (
    "acceptance_criteria",
    "tags",
    "assignees",
    "document_references",
    "endpoints",
    "data_contracts",
    "qa_notes",
)

def normalized_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return [stripped]
    return []

def is_positive(value, zero_ok=False):
    if isinstance(value, (int, float)):
        return value >= 0 if zero_ok else value > 0
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except Exception:
            return False
        return number >= 0 if zero_ok else number > 0
    return False

def detect_gaps(task):
    gaps = []
    for field in REQUIRED_TEXT_FIELDS:
        val = task.get(field)
        if not isinstance(val, str) or not val.strip():
            gaps.append(f"{field.replace('_', ' ')} missing or blank")
    for field in REQUIRED_LIST_FIELDS:
        if not normalized_list(task.get(field)):
            gaps.append(f"{field.replace('_', ' ')} missing or empty")
    if not is_positive(task.get("story_points")):
        gaps.append("story_points should be a positive integer (1-13)")
    if not is_positive(task.get("estimate")):
        gaps.append("estimate should be a positive number of hours")
    return gaps

def extract_keywords(story_data, task_data):
    parts = []
    for key in ("title", "narrative", "description"):
        value = story_data.get(key)
        if isinstance(value, str):
            parts.append(value)
    acceptance = story_data.get("acceptance_criteria")
    if isinstance(acceptance, list):
        parts.extend(str(item) for item in acceptance if item)
    for key in ("title", "description", "document_references", "endpoints", "data_contracts", "qa_notes", "tags"):
        value = task_data.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if item)
    joined = " ".join(parts).lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9\-_/]{2,}", joined)
    keywords = {token.strip("-_/") for token in tokens if len(token) > 3}
    return {kw for kw in keywords if kw and kw not in STOPWORDS}

def score_text(text, keywords):
    if not text:
        return 0
    lower = text.lower()
    return sum(lower.count(keyword) for keyword in keywords)

def summarize_text(text, char_limit):
    text = text.strip()
    if not text:
        return ""
    if char_limit > 0 and len(text) > char_limit:
        return text[:char_limit].rstrip() + "\n... (truncated; consult source for full details)"
    return text

def parse_context_sections(blob):
    sections = []
    current_title = "Context"
    current_lines = []
    for line in blob.splitlines():
        if line.startswith("----- FILE:"):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.split(":", 1)[-1].strip() or "Context"
            current_lines = []
        elif line.startswith("## "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip() or "Context"
            current_lines = []
        elif line.startswith("# "):
            continue
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))
    deduped = []
    seen = set()
    for title, text in sections:
        key = (title, text[:200])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((title, text))
    return deduped

def choose_context_sections(blob, keywords):
    sections = parse_context_sections(blob)
    if not sections:
        return []
    scored = []
    for title, text in sections:
        snippet = summarize_text(text, CONTEXT_SECTION_CHAR_LIMIT)
        if not snippet:
            continue
        summary = single_line_summary(snippet, CONTEXT_SECTION_SUMMARY_LIMIT)
        if not summary:
            continue
        score = score_text(text, keywords)
        scored.append((score, title, summary))
    scored.sort(key=lambda item: item[0], reverse=True)
    filtered = [entry for entry in scored if entry[0] > 0][:CONTEXT_SECTION_LIMIT]
    if not filtered:
        filtered = scored[:CONTEXT_SECTION_LIMIT]
    return [(title, summary) for _, title, summary in filtered if summary]

def load_sds_chunks(list_path):
    if not list_path or not list_path.exists():
        return []
    entries = []
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

def choose_sds_chunks(entries, keywords):
    if not entries:
        return [], [], 0
    scored = []
    for name, label, heading, content in entries:
        meta = " ".join(filter(None, (name, label, heading)))
        combined = f"{meta}\n{content}"
        score = score_text(combined, keywords)
        scored.append((score, name, label, heading, content))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [entry for entry in scored if entry[0] > 0][:SDS_CHUNK_LIMIT]
    if not selected:
        selected = scored[:SDS_CHUNK_LIMIT]
    overview_entries = selected[:SDS_OVERVIEW_LIMIT]
    prepared = []
    for _, name, label, heading, content in selected:
        ref = f"SDS {label}" if label else (heading or name)
        summary_text = summarize_text(content, SDS_SNIPPET_CHAR_LIMIT)
        summary = single_line_summary(summary_text, SDS_SNIPPET_SUMMARY_LIMIT)
        prepared.append((ref, summary))
    overview_list = []
    for _, name, label, heading, _ in overview_entries:
        ref = f"SDS {label}" if label else (heading or name)
        overview_list.append(ref)
    omitted_total = max(0, len(entries) - len(selected))
    return overview_list, prepared, omitted_total

def safe_excerpt(path, char_limit):
    if not path or not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""
    return single_line_summary(text, char_limit)

def load_other_tasks(db_path, story_slug, current_index):
    if not db_path or not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
    except Exception:
        return []
    lines = []
    try:
        for row in conn.execute(
            "SELECT position, task_id, title, status, dependencies_json FROM tasks WHERE story_slug = ? ORDER BY position",
            (story_slug,),
        ):
            pos = int(row["position"] or 0)
            if pos == current_index:
                continue
            identifier = (row["task_id"] or "").strip() or f"Task #{pos + 1:02d}"
            title = (row["title"] or "").strip() or "Untitled"
            status = (row["status"] or "pending").strip()
            deps_summary = ""
            deps_raw = row["dependencies_json"] or ""
            if deps_raw:
                try:
                    parsed = json.loads(deps_raw)
                    if isinstance(parsed, list) and parsed:
                        deps_summary = ", ".join(str(item).strip() for item in parsed if str(item).strip())
                except Exception:
                    deps_summary = deps_raw
            title_summary = single_line_summary(title, OTHER_TASKS_CHAR_LIMIT)
            line = f"- {identifier}: {title_summary} [status: {status}]"
            if deps_summary:
                deps_short = single_line_summary(deps_summary, max(30, OTHER_TASKS_CHAR_LIMIT // 2))
                if deps_short:
                    line += f" (deps: {deps_short})"
            line = single_line_summary(line, OTHER_TASKS_CHAR_LIMIT)
            lines.append(line)
            if len(lines) >= OTHER_TASKS_LIMIT:
                break
    finally:
        conn.close()
    return lines

def single_line_summary(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars].rstrip() + "…"
    return text

def _trim_field_text(value: str) -> str:
    if not isinstance(value, str):
        return value
    value = re.sub(r"\s+", " ", value.strip())
    if TASK_FIELD_CHAR_LIMIT > 0 and len(value) > TASK_FIELD_CHAR_LIMIT:
        value = value[:TASK_FIELD_CHAR_LIMIT].rstrip() + "…"
    return value

def _trim_field_list(items):
    if not isinstance(items, list):
        return []
    result = []
    for idx, item in enumerate(items):
        if idx >= TASK_FIELD_LIST_LIMIT:
            remainder = len(items) - TASK_FIELD_LIST_LIMIT
            if remainder > 0:
                result.append(f"... (+{remainder} more)")
            break
        if isinstance(item, str):
            result.append(_trim_field_text(item))
        else:
            result.append(item)
    return [entry for entry in result if entry not in ("", None, [])]

def build_compact_task(task: dict) -> dict:
    keys = [
        "id",
        "task_id",
        "status",
        "title",
        "description",
        "acceptance_criteria",
        "tags",
        "assignees",
        "dependencies",
        "document_references",
        "endpoints",
        "data_contracts",
        "qa_notes",
        "user_roles",
        "estimate",
        "story_points",
        "analytics",
        "observability",
        "policy",
        "idempotency",
        "rate_limits",
    ]
    snapshot = {}
    for key in keys:
        if key not in task:
            continue
        value = task.get(key)
        if isinstance(value, str):
            trimmed = _trim_field_text(value)
            if trimmed:
                snapshot[key] = trimmed
        elif isinstance(value, list):
            trimmed_list = _trim_field_list(value)
            if trimmed_list:
                snapshot[key] = trimmed_list
        elif value not in (None, ""):
            snapshot[key] = value
    return snapshot

keywords = extract_keywords(story, target_task)
context_sections = choose_context_sections(context_blob, keywords)

sds_snippets = []
sds_omitted = 0
entries = load_sds_chunks(sds_list_path)
if entries:
    _, sds_snippets, sds_omitted = choose_sds_chunks(entries, keywords)

pdr_excerpt = safe_excerpt(pdr_path, PDR_CHAR_LIMIT)
sql_excerpt = safe_excerpt(sql_path, SQL_CHAR_LIMIT)
other_tasks = load_other_tasks(db_path, story_slug, task_index)
gaps = detect_gaps(target_task)

story_summary = {
    "epic_id": epic_id,
    "epic_title": epic_title,
    "story_id": story_id,
    "story_title": story_title,
    "story_description": story_description,
    "story_roles": story_roles,
    "story_acceptance_criteria": story_acceptance,
}

with prompt_path.open("w", encoding="utf-8") as fh:
    fh.write(f"You are the {project_label}, refining a Jira task so it is implementation-ready.\n")
    fh.write("Fill in missing details using the focused context while preserving correct scope.\n\n")

    fh.write("## Story summary\n")
    json.dump(story_summary, fh, indent=2)
    fh.write("\n\n")

    fh.write("## Focused documentation references\n")
    if context_sections:
        for title, summary in context_sections:
            fh.write(f"- {title}: {summary}\n")
        fh.write("\n")
    else:
        fh.write("(No high-signal sections detected; reference the consolidated context if needed.)\n\n")

    if pdr_excerpt:
        fh.write("## PDR reference\n")
        fh.write(f"- {pdr_excerpt}\n\n")

    if sql_excerpt:
        fh.write("## Database schema reference\n")
        fh.write(f"- {sql_excerpt}\n\n")

    if sds_snippets:
        fh.write("## SDS references\n")
        for ref, summary in sds_snippets:
            if summary:
                fh.write(f"- {ref}: {summary}\n")
            else:
                fh.write(f"- {ref}\n")
        if sds_omitted > 0:
            fh.write(f"- ...(additional {sds_omitted} sections omitted; consult full SDS)\n")
        fh.write("\n")

    if other_tasks:
        fh.write("## Related tasks in backlog\n")
        fh.write("\n".join(other_tasks))
        fh.write("\n\n")

    fh.write("## Current task snapshot (trimmed)\n")
    json.dump(snapshot, fh, indent=2)
    fh.write("\n\n")

    if gaps:
        fh.write("## Fields to revise\n")
        for gap in gaps:
            fh.write(f"- {gap}\n")
        fh.write("\n")
    else:
        fh.write("## Fields to revise\n")
        fh.write("- No validation gaps detected; tighten clarity and references if helpful.\n\n")

    fh.write("## Requirements\n")
    fh.write("- Update only the fields above that need attention; keep correct data unchanged.\n")
    fh.write("- Cite documentation by identifier (SDS §#, SQL:table, API:/path) rather than pasting prose.\n")
    fh.write("- Fill in missing technical specifics (APIs, data contracts, QA, analytics, RBAC) using the references.\n")
    fh.write("- Keep estimates/story_points realistic and adjust tags, assignees, and dependencies when necessary.\n")
    fh.write("- Return the complete task as valid JSON with no markdown or commentary outside the object.\n\n")

    task_id = target_task.get("id") or target_task.get("task_id") or "TASK-ID"
    fh.write("## Output JSON schema\n")
    fh.write(
        "{\n"
        "  \"task\": {\n"
        f"    \"id\": \"{task_id}\",\n"
        "    \"title\": \"...\",\n"
        "    \"description\": \"...\",\n"
        "    \"acceptance_criteria\": [\"...\"],\n"
        "    \"tags\": [\"Web-FE\"],\n"
        "    \"assignees\": [\"FE dev\"],\n"
        "    \"estimate\": 5,\n"
        "    \"story_points\": 5,\n"
        "    \"dependencies\": [\"WEB-01-T00\"],\n"
        "    \"document_references\": [\"SDS §10.1.1\"],\n"
        "    \"endpoints\": [\"GET /api/v1/...\"],\n"
        "    \"data_contracts\": [\"Request payload...\"],\n"
        "    \"qa_notes\": [\"Tests...\"],\n"
        "    \"user_roles\": [\"Visitor\"]\n"
        "  }\n"
        "}\n"
    )
    fh.write("Return strictly valid JSON only.\n")