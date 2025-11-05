# Instruction
You are a structured-data assistant. Convert the following Jira backlog markdown into strict JSON.

## Requirements
- Output **only** valid JSON (no prose, no code fences).
- Structure: { "tasks": [ { "epic_id": str, "epic_title": str, "story_id": str, "story_title": str, "id": str, "title": str, "assignees": [str], "tags": [str], "story_points": str, "description": str, "acceptance_criteria": [str], "dependencies": [str] } ] }.
- Each task begins with a bold identifier such as **T18.5.2**; treat every such block as a separate task and capture its parent story/epic when present.
- Preserve bullet details verbatim inside the description and acceptance criteria lists. Do not repeat metadata (assignee/tags/story_points) inside the description.
- Use empty strings/arrays when information is missing.
- Do not include explanatory text.

## Jira Markdown
