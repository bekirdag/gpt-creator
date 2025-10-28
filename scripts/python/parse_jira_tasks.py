import json
import re
import sys
import time
from pathlib import Path

DASHES_PATTERN = r"[\\-\\u2012\\u2013\\u2014\\u2015]"


def normalise_list(value: str):
    cleaned = value.replace("+", ",").replace("/", ",").replace("&", ",")
    parts = [
        part.strip()
        for part in re.split(r",|;|\\band\\b", cleaned, flags=re.IGNORECASE)
        if part.strip()
    ]
    seen = set()
    ordered = []
    for item in parts:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(item)
    return ordered


def parse_jira(lines):
    epic_id = ""
    epic_title = ""
    story_id = ""
    story_title = ""
    tasks = []
    current = None
    section = None

    def flush_current():
        nonlocal current, section
        if current is None:
            return
        description_lines = [
            line.rstrip() for line in current["description_lines"] if line.strip()
        ]
        description = "\n".join(description_lines).strip()
        current["description"] = description
        del current["description_lines"]
        tasks.append(current)
        current = None
        section = None

    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            if current is not None and section == "description":
                current["description_lines"].append("")
            continue

        if stripped.lower() in {"**epic**", "**story**", "### **story**"}:
            continue

        epic_heading = re.match(
            r"^##\s+Epic\s+([A-Za-z0-9_.-]+)\s+" + DASHES_PATTERN + r"\s+(.*)$", stripped
        )
        epic_bold = re.match(
            r"^\*\*([Ee][A-Za-z0-9_.:-]+)\s*" + DASHES_PATTERN + r"\s*(.+?)\*\*$",
            stripped,
        )
        if epic_heading or epic_bold:
            flush_current()
            if epic_heading:
                epic_id = epic_heading.group(1).strip()
                epic_title = epic_heading.group(2).strip()
            else:
                epic_id = epic_bold.group(1).strip()
                epic_title = epic_bold.group(2).strip()
            story_id = ""
            story_title = ""
            continue

        story_heading = re.match(
            r"^###\s+Story\s+([A-Za-z0-9_.-]+)\s+" + DASHES_PATTERN + r"\s+(.*)$",
            stripped,
        )
        story_bold = re.match(
            r"^\*\*([Ss][A-Za-z0-9_.:-]+)\s*" + DASHES_PATTERN + r"\s*(.+?)\*\*$",
            stripped,
        )
        if story_heading or story_bold:
            flush_current()
            if story_heading:
                story_id = story_heading.group(1).strip()
                story_title = story_heading.group(2).strip()
            else:
                story_id = story_bold.group(1).strip()
                story_title = story_bold.group(2).strip()
            continue

        task_match = re.match(
            r"^\*\*([Tt][A-Za-z0-9_.:-]+)\s*" + DASHES_PATTERN + r"\s*(.+?)\*\*$",
            stripped,
        )
        if task_match:
            flush_current()
            task_id, task_title = task_match.groups()
            current = {
                "epic_id": epic_id,
                "epic_title": epic_title,
                "story_id": story_id,
                "story_title": story_title,
                "id": task_id.strip(),
                "title": task_title.strip(),
                "assignees": [],
                "tags": [],
                "estimate": "",
                "description_lines": [],
                "acceptance_criteria": [],
                "dependencies": [],
            }
            section = None
            continue

        if current is None:
            continue

        if "**Description:**" in stripped:
            section = "description"
            after = stripped.split("**Description:**", 1)[1].strip()
            if after:
                current["description_lines"].append(after)
            continue

        if "**Acceptance Criteria:**" in stripped:
            section = "ac"
            after = stripped.split("**Acceptance Criteria:**", 1)[1].strip()
            if after:
                current["acceptance_criteria"].append(after)
            continue

        if "**Dependencies:**" in stripped:
            section = "dependencies"
            after = stripped.split("**Dependencies:**", 1)[1].strip()
            if after:
                current["dependencies"] = normalise_list(after)
            continue

        if section == "ac":
            if stripped.startswith("*") or stripped.startswith("-"):
                current["acceptance_criteria"].append(stripped.lstrip("*- ").rstrip())
                continue
            else:
                section = None

        if section == "dependencies":
            if stripped.startswith("*") or stripped.startswith("-"):
                current["dependencies"].extend(
                    normalise_list(stripped.lstrip("*- "))
                )
                continue
            else:
                section = None

        segments = [seg.strip() for seg in re.split(r"[·•]", stripped) if seg.strip()]
        meta_consumed = False
        for seg in segments:
            plain = seg.replace("**", "")
            lower = plain.lower()
            if lower.startswith("assignee:"):
                value = plain.split(":", 1)[1].strip()
                if value:
                    current["assignees"] = normalise_list(value)
                    meta_consumed = True
            elif lower.startswith("tags:"):
                value = plain.split(":", 1)[1].strip()
                if value:
                    current["tags"] = normalise_list(value)
                    meta_consumed = True
            elif lower.startswith("estimate:"):
                value = plain.split(":", 1)[1].strip()
                if value and not current["estimate"]:
                    current["estimate"] = value
                    meta_consumed = True

        if section == "description" or (not meta_consumed and section is None):
            current["description_lines"].append(raw.rstrip())

    flush_current()

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tasks": tasks,
    }


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    jira_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    lines = jira_path.read_text(encoding="utf-8").splitlines()
    payload = parse_jira(lines)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
