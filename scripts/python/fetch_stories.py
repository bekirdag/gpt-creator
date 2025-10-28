import sqlite3
import sys
import textwrap

db_path, type_arg, item_children, progress_flag, task_details = sys.argv[1:6]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

def pluralize(value, singular, plural=None):
    try:
        count = int(value or 0)
    except Exception:
        count = 0
    if count == 1:
        return f"{count} {singular}"
    return f"{count} {plural or singular + 's'}"

def empty_counts():
    return {
        "stories": 0,
        "stories_complete": 0,
        "stories_in_progress": 0,
        "stories_pending": 0,
        "tasks": 0,
        "tasks_complete": 0,
        "tasks_in_progress": 0,
        "tasks_pending": 0,
    }

def fetch_stories():
    query = """
        SELECT story_slug, story_id, story_title, epic_key, epic_title,
               status, completed_tasks, total_tasks, sequence
        FROM stories
        ORDER BY COALESCE(sequence, 0), story_title COLLATE NOCASE
    """
    return [dict(row) for row in conn.execute(query)]

def fetch_epics():
    query = """
        SELECT epic_key, epic_id, title, slug
        FROM epics
        ORDER BY title COLLATE NOCASE
    """
    return [dict(row) for row in conn.execute(query)]

def fetch_task_counts():
    query = """
        SELECT story_slug,
               COUNT(*) AS total,
               SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'complete' THEN 1 ELSE 0 END) AS completed,
               SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'in-progress' THEN 1 ELSE 0 END) AS in_progress
        FROM tasks
        GROUP BY story_slug
    """
    counts = {}
    for row in conn.execute(query):
        counts[row["story_slug"]] = {
            "total": row["total"] or 0,
            "completed": row["completed"] or 0,
            "in_progress": row["in_progress"] or 0,
        }
    return counts

def fetch_tasks_for_story(slug):
    query = """
        SELECT position, task_id, title, status, estimate
        FROM tasks
        WHERE story_slug = ?
        ORDER BY position
    """
    return [dict(row) for row in conn.execute(query, (slug,))]

UNASSIGNED_KEY = "__unassigned__"
UNASSIGNED_LABEL = "Unassigned backlog"

def canonical_epic_descriptor(epic_id=None, epic_slug=None, epic_title=None):
    epic_id = (epic_id or "").strip()
    epic_slug = (epic_slug or "").strip()
    epic_title = (epic_title or "").strip()
    for candidate in (epic_slug, epic_id, epic_title):
        if candidate:
            norm = candidate.lower()
            display_title = epic_title or epic_slug or epic_id
            return norm, epic_id, epic_slug, display_title
    return UNASSIGNED_KEY, "", "", UNASSIGNED_LABEL

def derive_pseudo_epic(identifier):
    if not identifier:
        return None
    clean = identifier.replace("/", "-").replace("_", "-")
    parts = [part for part in clean.split("-") if part]
    if len(parts) >= 2:
        return "-".join(parts[:2]).upper()
    if len(parts) == 1:
        return parts[0].upper()
    return None

def determine_epic_for_story(story):
    norm, epic_id, epic_slug, epic_title = canonical_epic_descriptor(
        story.get("epic_id"),
        story.get("epic_key"),
        story.get("epic_title"),
    )
    if norm != UNASSIGNED_KEY:
        return norm, epic_id, epic_slug or epic_id.lower(), epic_title

    for candidate in (story.get("story_id"), story.get("story_slug")):
        pseudo = derive_pseudo_epic((candidate or "").strip())
        if pseudo:
            return pseudo.lower(), pseudo, pseudo.lower(), pseudo
    return norm, epic_id, epic_slug, epic_title

def format_epic_label(epic_id, epic_slug, epic_title):
    epic_title = (epic_title or "").strip()
    epic_id = (epic_id or "").strip()
    epic_slug = (epic_slug or "").strip()
    if epic_title and epic_title != UNASSIGNED_LABEL:
        if epic_id and epic_id.lower() not in epic_title.lower():
            return f"{epic_title} [{epic_id}]"
        return epic_title
    if epic_id:
        return epic_id
    if epic_slug:
        return epic_slug
    return UNASSIGNED_LABEL

def summarise_epics(stories, task_counts):
    summary = {}
    for story in stories:
        norm_key, epic_id, epic_slug, epic_title = determine_epic_for_story(story)
        entry = summary.setdefault(
            norm_key,
            {
                "counts": empty_counts(),
                "epic_id": epic_id,
                "epic_slug": epic_slug,
                "epic_title": epic_title,
            },
        )
        if epic_id and not entry["epic_id"]:
            entry["epic_id"] = epic_id
        if epic_slug and not entry["epic_slug"]:
            entry["epic_slug"] = epic_slug
        story_epic_title = (story.get("epic_title") or "").strip()
        if story_epic_title and entry["epic_title"] in (UNASSIGNED_LABEL, "", None):
            entry["epic_title"] = story_epic_title

        counts = entry["counts"]
        counts["stories"] += 1
        status = (story.get("status") or "pending").strip().lower()
        if status == "complete":
            counts["stories_complete"] += 1
        elif status in {"in-progress", "in progress"}:
            counts["stories_in_progress"] += 1
        else:
            counts["stories_pending"] += 1

        counts_dict = task_counts.get(story["story_slug"], {})
        total = counts_dict.get("total", story.get("total_tasks") or 0) or 0
        completed = counts_dict.get("completed", story.get("completed_tasks") or 0) or 0
        in_progress = counts_dict.get("in_progress", 0) or 0
        pending = max(total - completed - in_progress, 0)

        counts["tasks"] += total
        counts["tasks_complete"] += completed
        counts["tasks_in_progress"] += in_progress
        counts["tasks_pending"] += pending
    return summary

def build_epic_entries(epics, stories, summary):
    epics_by_norm = {}
    for epic in epics:
        norm, epic_id, epic_slug, epic_title = canonical_epic_descriptor(
            epic.get("epic_id"),
            epic.get("epic_key") or epic.get("slug"),
            epic.get("title"),
        )
        epics_by_norm[norm] = {
            "epic_id": epic_id,
            "slug": (epic.get("slug") or epic.get("epic_key") or epic_slug or "").strip(),
            "title": epic_title or format_epic_label(epic_id, epic_slug, epic.get("title")),
            "raw": dict(epic),
        }

    stories_by_norm = {}
    for story in stories:
        norm, _, _, _ = determine_epic_for_story(story)
        stories_by_norm.setdefault(norm, []).append(story)

    entries = []
    all_keys = set(summary.keys()) | set(epics_by_norm.keys())
    if not all_keys:
        all_keys.add(UNASSIGNED_KEY)

    for norm in all_keys:
        meta = summary.get(norm, {})
        epic_info = epics_by_norm.get(norm, {})
        counts = meta.get("counts") or empty_counts()
        epic_id = meta.get("epic_id") or epic_info.get("epic_id") or ""
        epic_slug = meta.get("epic_slug") or epic_info.get("slug") or ""
        epic_title = meta.get("epic_title") or epic_info.get("title") or UNASSIGNED_LABEL
        label = format_epic_label(epic_id, epic_slug, epic_title)
        entries.append(
            {
                "key": None if norm == UNASSIGNED_KEY else norm,
                "label": label,
                "counts": counts,
                "stories": stories_by_norm.get(norm, []),
                "epic": {
                    "epic_id": epic_id,
                    "slug": epic_slug,
                    "title": epic_title,
                },
            }
        )

    entries.sort(key=lambda item: (item["key"] is None, item["label"].lower()))
    return entries

def print_table(headers, rows):
    if not rows:
        print("No records found.")
        return
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(str(cell)))

    def fmt(row):
        return "  ".join(str(cell).ljust(widths[idx]) for idx, cell in enumerate(row))

    print(fmt(list(headers)))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))

stories = fetch_stories()
epics = fetch_epics()
task_counts = fetch_task_counts()
summary = summarise_epics(stories, task_counts)
entries = build_epic_entries(epics, stories, summary)

stories_by_slug = {}
stories_by_id = {}
for story in stories:
    slug = (story.get("story_slug") or "").strip().lower()
    if slug:
        stories_by_slug[slug] = story
    sid = (story.get("story_id") or "").strip().lower()
    if sid:
        stories_by_id[sid] = story

epic_lookup = {}
for entry in entries:
    epic = entry.get("epic") or {}
    for candidate in (epic.get("slug"), epic.get("epic_id"), epic.get("title"), entry["label"]):
        if candidate and str(candidate).strip():
            epic_lookup[str(candidate).strip().lower()] = entry
    if entry["key"] is None:
        for alias in ("unassigned", "none", "no-epic", "noepic"):
            epic_lookup[alias] = entry

def print_epics_table():
    if not entries:
        print("No epics found in the backlog.")
        return
    headers = ["Epic ID", "Slug", "Title", "Stories", "Tasks", "Progress"]
    rows = []
    for entry in entries:
        counts = entry.get("counts") or empty_counts()
        epic = entry.get("epic") or {}
        epic_id = (epic.get("epic_id") or "").strip() or "-"
        slug = (epic.get("slug") or "").strip() or "-"
        title = entry["label"]
        stories_desc = pluralize(counts["stories"], "story", "stories")
        story_bits = []
        if counts["stories_complete"]:
            story_bits.append(f"{counts['stories_complete']} complete")
        if counts["stories_in_progress"]:
            story_bits.append(f"{counts['stories_in_progress']} in-progress")
        if counts["stories_pending"]:
            story_bits.append(f"{counts['stories_pending']} pending")
        if story_bits:
            stories_desc += f" ({', '.join(story_bits)})"

        tasks_desc = pluralize(counts["tasks"], "task")
        task_bits = []
        if counts["tasks_complete"]:
            task_bits.append(f"{counts['tasks_complete']} complete")
        if counts["tasks_in_progress"]:
            task_bits.append(f"{counts['tasks_in_progress']} in-progress")
        if counts["tasks_pending"]:
            task_bits.append(f"{counts['tasks_pending']} pending")
        if task_bits:
            tasks_desc += f" ({', '.join(task_bits)})"

        total_tasks = counts["tasks"] or 0
        progress = 0.0
        if total_tasks:
            progress = (counts["tasks_complete"] / total_tasks) * 100
        rows.append([
            epic_id,
            slug,
            title,
            stories_desc,
            tasks_desc,
            f"{progress:5.1f}%",
        ])
    print_table(headers, rows)

def print_story_children(entry, identifier):
    stories_for_epic = entry.get("stories") or []
    if not stories_for_epic:
        print(f"No stories found for epic '{identifier}'.")
        return
    headers = ["Story Slug", "Title", "Status", "Epic", "Tasks", "Progress"]
    rows = []
    for story in sorted(stories_for_epic, key=lambda s: (s.get("sequence") or 0, (s.get("story_title") or "").lower())):
        slug = (story.get("story_slug") or "").strip()
        title = (story.get("story_title") or story.get("story_id") or slug or "Story").strip()
        epic_title = (story.get("epic_title") or entry["label"]).strip()
        counts = task_counts.get(story.get("story_slug"), {})
        total = counts.get("total", story.get("total_tasks") or 0) or 0
        complete = counts.get("completed", story.get("completed_tasks") or 0) or 0
        in_progress = counts.get("in_progress", 0) or 0
        pending = max(total - complete - in_progress, 0)
        status, progress, tasks_desc = compute_story_metrics(total, complete, in_progress, pending, story.get("status"))
        rows.append([
            slug or (story.get("story_id") or "-"),
            title,
            status,
            epic_title,
            tasks_desc,
            f"{progress:5.1f}%",
        ])
    print_table(headers, rows)

def truncate(text, width=60):
    text = (text or "").strip()
    if not text:
        return "-"
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."

def print_task_children(story):
    slug = story.get("story_slug")
    tasks = fetch_tasks_for_story(slug)
    if not tasks:
        print(f"No tasks found for story '{slug or story.get('story_id') or story.get('story_title')}'.")
        return
    headers = ["#", "Task ID", "Title", "Status", "Estimate"]
    rows = []
    for task in tasks:
        position = task.get("position")
        index = str((position if position is not None else 0) + 1)
        task_id = (task.get("task_id") or "").strip() or "-"
        title = truncate(task.get("title"), width=80)
        status = (task.get("status") or "pending").strip().lower().replace("_", "-")
        estimate = (task.get("estimate") or "").strip() or "-"
        rows.append([index, task_id, title, status, estimate])
    print_table(headers, rows)

def compute_story_metrics(total, complete, in_progress, pending, status_field):
    status_field = (status_field or "pending").strip().lower().replace("_", "-")
    if total > 0:
        if complete >= total and in_progress == 0 and pending == 0:
            status = "complete"
            progress = 100.0
        elif complete > 0 or in_progress > 0:
            status = "in-progress"
            progress = (complete / total) * 100
        else:
            status = "pending"
            progress = 0.0
    else:
        status = status_field or "pending"
        progress = 100.0 if status == "complete" else 0.0

    if total > 0:
        tasks_desc = f"{complete}/{total} complete"
        if in_progress:
            tasks_desc += f", {in_progress} in-progress"
        if pending and status != "complete":
            tasks_desc += f", {pending} pending"
    else:
        tasks_desc = "0 tasks"

    return status, progress, tasks_desc

def show_item_children(identifier):
    if not identifier:
        return
    ident = identifier.strip().lower()
    entry = epic_lookup.get(ident)
    if entry:
        label = entry["label"]
        epic = entry.get("epic") or {}
        epic_ident = (epic.get("epic_id") or epic.get("slug") or entry["label"] or "unassigned").strip()
        print(f"Stories for epic: {label} ({epic_ident})")
        print_story_children(entry, identifier)
        return

    if ident in stories_by_slug:
        story = stories_by_slug[ident]
    elif ident in stories_by_id:
        story = stories_by_id[ident]
    else:
        story = None

    if story:
        title = story.get("story_title") or story.get("story_id") or story.get("story_slug")
        print(f"Tasks for story: {title} ({story.get('story_slug')})")
        print_task_children(story)
        return

    print(f"No epic or story found for identifier '{identifier}'.", file=sys.stderr)
    sys.exit(1)

def print_stories_overview():
    if not stories:
        print("No stories found in the backlog.")
        return
    headers = ["Story Slug", "Story ID", "Title", "Epic", "Status", "Tasks", "Progress"]
    rows = []
    for story in sorted(
        stories,
        key=lambda s: (
            (s.get("epic_title") or "").lower(),
            s.get("sequence") or 0,
            (s.get("story_title") or "").lower(),
        ),
    ):
        slug = (story.get("story_slug") or "").strip()
        story_id = (story.get("story_id") or "").strip()
        title = (story.get("story_title") or story_id or slug or "Story").strip()
        epic_title = (story.get("epic_title") or "Unassigned").strip()
        counts = task_counts.get(story.get("story_slug"), {})
        total = counts.get("total", story.get("total_tasks") or 0) or 0
        complete = counts.get("completed", story.get("completed_tasks") or 0) or 0
        in_progress = counts.get("in_progress", 0) or 0
        pending = max(total - complete - in_progress, 0)
        status, progress, tasks_desc = compute_story_metrics(total, complete, in_progress, pending, story.get("status"))
        rows.append([
            slug or "-",
            story_id or "-",
            title,
            epic_title,
            status,
            tasks_desc,
            f"{progress:5.1f}%",
        ])
    print_table(headers, rows)

def print_task_details(task_identifier):
    if not task_identifier:
        return
    ident = task_identifier.strip().lower()
    query = """
        SELECT *
        FROM tasks
        WHERE LOWER(COALESCE(task_id, '')) = ?
           OR CAST(id AS TEXT) = ?
    """
    row = conn.execute(query, (ident, ident)).fetchone()
    if row is None:
        print(f"No task found for identifier '{task_identifier}'.", file=sys.stderr)
        sys.exit(1)

    print("Task details")
    print("------------")

    def emit(label, value):
        text = value if isinstance(value, str) else ("" if value is None else str(value))
        if isinstance(text, str):
            text = text.strip()
        print(f"{label}: {text if text else '-'}")

    emit("Task ID", row["task_id"])
    emit("Story Slug", row["story_slug"])
    emit("Story Title", row["story_title"])
    emit("Epic", row["epic_title"] or row["epic_key"])
    emit("Status", row["status"])
    emit("Estimate", row["estimate"])
    emit("Assignees", row["assignee_text"])
    emit("Tags", row["tags_text"])
    emit("Dependencies", row["dependencies_text"])
    emit("Story Points", row["story_points"])
    emit("Document Reference", row["document_reference"])
    emit("Idempotency", row["idempotency"])
    emit("Rate Limits", row["rate_limits"])
    emit("RBAC", row["rbac"])
    emit("Messaging/Workflows", row["messaging_workflows"])
    emit("Performance Targets", row["performance_targets"])
    emit("Observability", row["observability"])
    emit("Endpoints", row["endpoints"])
    emit("Sample Create Request", row["sample_create_request"])
    emit("Sample Create Response", row["sample_create_response"])
    emit("Acceptance Criteria", row["acceptance_text"])
    emit("User Story Ref", row["user_story_ref_id"])
    emit("Epic Ref", row["epic_ref_id"])
    emit("Started At", row["started_at"])
    emit("Completed At", row["completed_at"])
    emit("Last Run", row["last_run"])
    emit("Created At", row["created_at"])
    emit("Updated At", row["updated_at"])

def print_progress():
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'complete' THEN 1 ELSE 0 END) AS complete,
          SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'in-progress' THEN 1 ELSE 0 END) AS in_progress
        FROM tasks
        """
    ).fetchone()
    total = row["total"] or 0
    complete = row["complete"] or 0
    in_progress = row["in_progress"] or 0
    pending = max(total - complete - in_progress, 0)
    percent = (complete / total * 100) if total else 0.0
    bar_length = 30
    filled_units = int(round((percent / 100) * bar_length))
    filled_units = min(bar_length, max(0, filled_units))
    bar = "#" * filled_units + "-" * (bar_length - filled_units)
    print("Overall backlog progress")
    print(f"Tasks complete: {complete}/{total} ({percent:0.1f}%)")
    print(f"In-progress: {in_progress}, Pending: {pending}")
    print(f"[{bar}]")

try:
    printed = False
    if type_arg:
        t = type_arg.strip().lower()
        if t == "epics":
            print_epics_table()
            printed = True
        elif t == "stories":
            print_stories_overview()
            printed = True
        else:
            print(f"Unsupported backlog type: {type_arg}", file=sys.stderr)
            sys.exit(1)
        if printed and (item_children or progress_flag == "1" or task_details):
            print()
    if item_children:
        show_item_children(item_children)
        printed = True
        if progress_flag == "1" or task_details:
            print()
    if progress_flag == "1":
        print_progress()
        printed = True
        if task_details:
            print()
    if task_details:
        print_task_details(task_details)
finally:
    conn.close()