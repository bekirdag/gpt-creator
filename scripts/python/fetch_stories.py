import re
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

args = list(sys.argv[1:])
while len(args) < 6:
    args.append("")
db_path, type_arg, item_children, progress_flag, task_details, dag_limit = args[:6]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row


def infer_project_root(db_file: str) -> Path:
    resolved = Path(db_file).resolve()
    for parent in resolved.parents:
        if parent.name == ".gpt-creator":
            return parent.parent
    return resolved.parent


PROJECT_ROOT = infer_project_root(db_path)
STATUS_OVERRIDE_DIR = PROJECT_ROOT / ".gpt-creator" / "logs" / "status-overrides"
_RECENT_SUBJECTS = None


def _load_status_overrides() -> set[str]:
    tasks: set[str] = set()
    if not STATUS_OVERRIDE_DIR.exists():
        return tasks
    for path in STATUS_OVERRIDE_DIR.glob("*.applied"):
        try:
            name = path.stem.upper()
            if name:
                tasks.add(name)
        except OSError:
            continue
    return tasks


def _recent_commit_subjects() -> list[str]:
    global _RECENT_SUBJECTS
    if _RECENT_SUBJECTS is not None:
        return _RECENT_SUBJECTS
    try:
        output = subprocess.check_output(
            ["git", "log", "-n", "40", "--pretty=format:%s"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        _RECENT_SUBJECTS = []
        return _RECENT_SUBJECTS
    _RECENT_SUBJECTS = [line.strip() for line in output.splitlines() if line.strip()]
    return _RECENT_SUBJECTS


STATUS_OVERRIDE_TASKS = _load_status_overrides()


def _task_column_exists(column: str) -> bool:
    try:
        info = conn.execute("PRAGMA table_info(tasks)").fetchall()
    except sqlite3.DatabaseError:
        return False
    column_norm = (column or "").strip().lower()
    for entry in info:
        name = (entry[1] or "").strip().lower()
        if name == column_norm:
            return True
    return False


HAS_TASK_ESTIMATE_COLUMN = _task_column_exists("estimate")

DONE_PREFIXES = (
    "complete",
    "completed",
    "done",
    "skipped",
    "skip",
)


def normalise_status(value: str) -> str:
    text = (value or "").strip().lower()
    return text.replace("_", "-")


def status_is_completed(value: str) -> bool:
    status = normalise_status(value)
    if not status:
        return False
    tokens = [status]
    split_tokens = [token for token in re.split(r"[^a-z0-9]+", status) if token]
    if split_tokens:
        tokens.extend(split_tokens)
    for prefix in DONE_PREFIXES:
        for token in tokens:
            if token.startswith(prefix):
                return True
    return False


def apply_status_override(task_id: str, status: str) -> str:
    normalised = normalise_status(status)
    if normalised != "completed-no-changes":
        return status
    clean_id = (task_id or "").strip().upper()
    if not clean_id:
        return status
    if clean_id in STATUS_OVERRIDE_TASKS:
        return "complete"
    subjects = _recent_commit_subjects()
    for subject in subjects:
        if clean_id in subject.upper():
            STATUS_OVERRIDE_TASKS.add(clean_id)
            return "complete"
    return status


def status_is_in_progress(value: str) -> bool:
    status = normalise_status(value)
    if not status:
        return False
    if status == "in-progress" or status == "in progress":
        return True
    if status.startswith("in-progress"):
        return True
    return False


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


def count_remaining_tasks(cur: sqlite3.Connection) -> int:
    remaining = 0
    for row in cur.execute("SELECT status, task_id FROM tasks"):
        status = row["status"] if isinstance(row, sqlite3.Row) else row[0]
        task_id = row["task_id"] if isinstance(row, sqlite3.Row) else row[1] if len(row) > 1 else ""
        status = apply_status_override(task_id, status)
        if not status_is_completed(status):
            remaining += 1
    return remaining

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
    counts = {}
    for row in conn.execute("SELECT story_slug, status, task_id FROM tasks"):
        slug = (row["story_slug"] or "").strip()
        entry = counts.setdefault(slug, {"total": 0, "completed": 0, "in_progress": 0})
        entry["total"] += 1
        status = apply_status_override(row["task_id"], row["status"])
        if status_is_completed(status):
            entry["completed"] += 1
        elif status_is_in_progress(status):
            entry["in_progress"] += 1
    return counts

def fetch_tasks_for_story(slug):
    story_points_expr = "story_points"
    if HAS_TASK_ESTIMATE_COLUMN:
        story_points_expr = "COALESCE(story_points, estimate)"
    query = f"""
        SELECT position, task_id, title, status, {story_points_expr} AS story_points, global_order
        FROM tasks
        WHERE story_slug = ?
        ORDER BY position
    """
    results = []
    for row in conn.execute(query, (slug,)):
        row_dict = dict(row)
        row_dict["status"] = apply_status_override(row_dict.get("task_id"), row_dict.get("status"))
        results.append(row_dict)
    return results

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
    headers = ["#", "Order", "Task ID", "Title", "Status", "Story Points"]
    rows = []
    for task in tasks:
        position = task.get("position")
        index = str((position if position is not None else 0) + 1)
        global_order = task.get("global_order")
        order_display = "-"
        try:
            order_int = int(global_order)
        except (TypeError, ValueError):
            order_int = 0
        if order_int > 0:
            order_display = str(order_int)
        task_id = (task.get("task_id") or "").strip() or "-"
        title = truncate(task.get("title"), width=80)
        status = (task.get("status") or "pending").strip().lower().replace("_", "-")
        points_value = task.get("story_points")
        if points_value is None:
            story_points = "-"
        else:
            story_points = str(points_value).strip() or "-"
        rows.append([index, order_display, task_id, title, status, story_points])
    print_table(headers, rows)

def compute_story_metrics(total, complete, in_progress, pending, status_field):
    status_field = normalise_status(status_field or "pending")
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
        progress = 100.0 if status_is_completed(status) else 0.0

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


def print_global_order_queue(limit: int) -> None:
    if limit <= 0:
        limit = 20
    query = """
        SELECT global_order,
               story_slug,
               task_id,
               title,
               status,
               priority,
               due_at,
               COALESCE(points, story_points) AS points
          FROM tasks
         WHERE global_order > 0
         ORDER BY global_order ASC
         LIMIT ?
    """
    rows = conn.execute(query, (limit,)).fetchall()
    if not rows:
        print("No tasks have been ordered yet (global_order column is empty).")
        return

    headers = ["Order", "Story", "Task ID", "Title", "Status", "Priority", "Due", "Points"]
    table_rows: list[list[str]] = []
    for row in rows:
        order_value = row["global_order"]
        story_slug = (row["story_slug"] or "").strip()
        task_id = (row["task_id"] or "").strip() or "-"
        title = truncate(row["title"], width=80)
        status = normalise_status(row["status"] or "pending")
        priority = row["priority"] if row["priority"] is not None else "-"
        due = (row["due_at"] or "").strip() or "-"
        points = row["points"] if row["points"] is not None else "-"
        table_rows.append([
            str(order_value),
            story_slug or "-",
            task_id,
            title,
            status,
            str(priority),
            due,
            str(points),
        ])

    print("Next tasks by DAG priority")
    print_table(headers, table_rows)

def print_progress():
    total = 0
    complete = 0
    in_progress = 0
    for row in conn.execute("SELECT status FROM tasks"):
        status = row["status"]
        total += 1
        if status_is_completed(status):
            complete += 1
        elif status_is_in_progress(status):
            in_progress += 1
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
        if printed and (item_children or progress_flag == "1" or task_details or dag_limit):
            print()
    if item_children:
        show_item_children(item_children)
        printed = True
        if progress_flag == "1" or task_details or dag_limit:
            print()
    if progress_flag == "1":
        print_progress()
        printed = True
        if task_details or dag_limit:
            print()
    if task_details:
        print_task_details(task_details)
        printed = True
        if dag_limit:
            print()
    if dag_limit:
        try:
            limit_val = int(dag_limit)
        except (TypeError, ValueError):
            limit_val = 0
        if limit_val <= 0:
            limit_val = 20
        print_global_order_queue(limit_val)
        printed = True
finally:
    canonical_remaining = count_remaining_tasks(conn)
    if 'printed' in locals() and printed:
        print()
    print(f"Remaining tasks (canonical): {canonical_remaining}")
    conn.close()
def print_global_order_queue(limit: int) -> None:
    query = """
        SELECT global_order, story_slug, task_id, title, status
          FROM tasks
         WHERE global_order > 0
         ORDER BY global_order ASC
         LIMIT ?
    """
    rows = []
    for row in conn.execute(query, (limit,)):
        order_value = row["global_order"]
        try:
            order_int = int(order_value)
        except (TypeError, ValueError):
            order_int = 0
        if order_int <= 0:
            continue
        story_slug = (row["story_slug"] or "").strip()
        task_id = (row["task_id"] or "").strip() or "-"
        title = truncate(row["title"], width=80)
        status = normalise_status(row["status"] or "pending")
        rows.append([str(order_int), story_slug or "-", task_id, title, status])

    headers = ["Order", "Story", "Task ID", "Title", "Status"]
    if not rows:
        print(f"No tasks found with global order.")
    else:
        print("Next tasks by DAG priority")
        print_table(headers, rows)
