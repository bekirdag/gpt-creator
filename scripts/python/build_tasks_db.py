import hashlib
import json
import re
import sqlite3
import sys
import time
from collections import OrderedDict
from pathlib import Path


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "item"


def story_key_for(task: dict) -> str:
    return "|".join(
        [
            (task.get("story_id") or "").strip(),
            (task.get("story_title") or "").strip(),
            (task.get("epic_id") or "").strip(),
            (task.get("epic_title") or "").strip(),
        ]
    )


def list_to_text(values):
    if not values:
        return None
    return ", ".join(str(item).strip() for item in values if str(item).strip()) or None


def as_text(value):
    if isinstance(value, list):
        return list_to_text(value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def normalise_title(value):
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def stable_task_uid(story_slug, task_id, title, position):
    slug = (story_slug or "").strip().lower()
    identifier = (task_id or "").strip().lower()
    if not identifier:
        identifier = f"pos:{position}"
    key = f"{slug}|{identifier}|{normalise_title(title)}"
    return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()


def parse_tasks(tasks_json_path: Path) -> tuple[list, str]:
    payload = json.loads(tasks_json_path.read_text(encoding="utf-8"))
    all_tasks = payload.get("tasks") or []
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    grouped = OrderedDict()
    for task in all_tasks:
        key = story_key_for(task)
        grouped.setdefault(
            key,
            {
                "story_id": (task.get("story_id") or "").strip(),
                "story_title": (task.get("story_title") or "").strip(),
                "epic_id": (task.get("epic_id") or "").strip(),
                "epic_title": (task.get("epic_title") or "").strip(),
                "tasks": [],
            },
        )
        grouped[key]["tasks"].append(task)

    return grouped, generated_at


def main() -> int:
    if len(sys.argv) < 4:
        return 1

    tasks_json_path = Path(sys.argv[1])
    db_path = Path(sys.argv[2])
    force = sys.argv[3] == "1"

    grouped, generated_at = parse_tasks(tasks_json_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")

    def ensure_table():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS epics (
              epic_key TEXT PRIMARY KEY,
              epic_id TEXT,
              title TEXT,
              slug TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stories (
              story_slug TEXT PRIMARY KEY,
              story_key TEXT UNIQUE,
              story_id TEXT,
              story_title TEXT,
              epic_key TEXT,
              epic_title TEXT,
              sequence INTEGER,
              status TEXT,
              completed_tasks INTEGER,
              total_tasks INTEGER,
              last_run TEXT,
              updated_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(epic_key) REFERENCES epics(epic_key)
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              story_slug TEXT NOT NULL,
              position INTEGER NOT NULL,
              task_id TEXT,
              title TEXT,
              description TEXT,
              estimate TEXT,
              assignees_json TEXT,
              tags_json TEXT,
              acceptance_json TEXT,
              dependencies_json TEXT,
              tags_text TEXT,
              story_points TEXT,
              dependencies_text TEXT,
              assignee_text TEXT,
              document_reference TEXT,
              idempotency TEXT,
              rate_limits TEXT,
              rbac TEXT,
              messaging_workflows TEXT,
              performance_targets TEXT,
              observability TEXT,
              acceptance_text TEXT,
              endpoints TEXT,
              sample_create_request TEXT,
              sample_create_response TEXT,
              user_story_ref_id TEXT,
              epic_ref_id TEXT,
              status TEXT NOT NULL DEFAULT 'pending',
              status_reason TEXT,
              evidence_ptr TEXT,
              doc_refs TEXT,
              last_verified_commit TEXT,
              last_attempt_signature TEXT,
              last_changes_count INTEGER,
              last_outcome_reason TEXT,
              locked_by TEXT,
              locked_by_migration INTEGER DEFAULT 0,
              migration_epoch INTEGER DEFAULT 0,
              reopened_by_migration_at TEXT,
              reopened_by_migration INTEGER DEFAULT 0,
              started_at TEXT,
              completed_at TEXT,
              last_run TEXT,
              story_id TEXT,
              story_title TEXT,
              epic_key TEXT,
              epic_title TEXT,
              uid TEXT,
              updated_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE(story_slug, position),
              UNIQUE(uid),
              FOREIGN KEY(story_slug) REFERENCES stories(story_slug)
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS task_progress (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id INTEGER,
              story_slug TEXT NOT NULL,
              task_position INTEGER NOT NULL,
              run_stamp TEXT,
              status TEXT,
              log_path TEXT,
              prompt_path TEXT,
              output_path TEXT,
              attempts INTEGER,
              tokens_total INTEGER,
              tokens_prompt_estimate INTEGER,
              llm_prompt_tokens INTEGER,
              llm_completion_tokens INTEGER,
              duration_seconds INTEGER,
              apply_status TEXT,
              changes_applied INTEGER,
              changes_count INTEGER,
              notes_json TEXT,
              written_json TEXT,
              patched_json TEXT,
              commands_json TEXT,
              attempt_signature TEXT,
              outcome_reason TEXT,
              occurred_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS doc_observations (
              task_id TEXT NOT NULL,
              doc_hash TEXT NOT NULL,
              tokens INTEGER NOT NULL,
              first_seen_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
              PRIMARY KEY (task_id, doc_hash)
            )
        """
        )

    ensure_table()
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_uid ON tasks(uid)")

    def column_exists(table: str, column: str) -> bool:
        cur.execute(f"PRAGMA table_info({table})")
        return any(row["name"] == column for row in cur.fetchall())

    def ensure_column(table: str, column: str, definition: str):
        if not column_exists(table, column):
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    ensure_column("task_progress", "tokens_prompt_estimate", "INTEGER")
    ensure_column("task_progress", "llm_prompt_tokens", "INTEGER")
    ensure_column("task_progress", "llm_completion_tokens", "INTEGER")

    ensure_column("stories", "completed_tasks", "INTEGER")
    ensure_column("stories", "total_tasks", "INTEGER")
    ensure_column("stories", "status", "TEXT DEFAULT 'pending'")
    ensure_column("stories", "last_run", "TEXT")
    ensure_column("stories", "epic_title", "TEXT")

    ensure_column("tasks", "story_id", "TEXT")
    ensure_column("tasks", "story_title", "TEXT")
    ensure_column("tasks", "epic_key", "TEXT")
    ensure_column("tasks", "epic_title", "TEXT")
    ensure_column("tasks", "status", "TEXT DEFAULT 'pending'")
    ensure_column("tasks", "started_at", "TEXT")
    ensure_column("tasks", "completed_at", "TEXT")
    ensure_column("tasks", "last_run", "TEXT")
    ensure_column("tasks", "tags_text", "TEXT")
    ensure_column("tasks", "story_points", "TEXT")
    ensure_column("tasks", "dependencies_text", "TEXT")
    ensure_column("tasks", "assignee_text", "TEXT")
    ensure_column("tasks", "document_reference", "TEXT")
    ensure_column("tasks", "idempotency", "TEXT")
    ensure_column("tasks", "rate_limits", "TEXT")
    ensure_column("tasks", "rbac", "TEXT")
    ensure_column("tasks", "messaging_workflows", "TEXT")
    ensure_column("tasks", "performance_targets", "TEXT")
    ensure_column("tasks", "observability", "TEXT")
    ensure_column("tasks", "acceptance_text", "TEXT")
    ensure_column("tasks", "endpoints", "TEXT")
    ensure_column("tasks", "sample_create_request", "TEXT")
    ensure_column("tasks", "sample_create_response", "TEXT")
    ensure_column("tasks", "user_story_ref_id", "TEXT")
    ensure_column("tasks", "epic_ref_id", "TEXT")
    ensure_column("tasks", "last_log_path", "TEXT")
    ensure_column("tasks", "last_prompt_path", "TEXT")
    ensure_column("tasks", "last_output_path", "TEXT")
    ensure_column("tasks", "last_attempts", "INTEGER")
    ensure_column("tasks", "last_tokens_total", "INTEGER")
    ensure_column("tasks", "last_prompt_tokens_estimate", "INTEGER")
    ensure_column("tasks", "last_llm_prompt_tokens", "INTEGER")
    ensure_column("tasks", "last_llm_completion_tokens", "INTEGER")
    ensure_column("tasks", "last_duration_seconds", "INTEGER")
    ensure_column("tasks", "last_apply_status", "TEXT")
    ensure_column("tasks", "last_changes_applied", "INTEGER")
    ensure_column("tasks", "last_notes_json", "TEXT")
    ensure_column("tasks", "last_written_json", "TEXT")
    ensure_column("tasks", "last_patched_json", "TEXT")
    ensure_column("tasks", "last_commands_json", "TEXT")
    ensure_column("tasks", "last_progress_at", "TEXT")
    ensure_column("tasks", "last_progress_run", "TEXT")
    ensure_column("tasks", "status_reason", "TEXT")
    ensure_column("tasks", "evidence_ptr", "TEXT")
    ensure_column("tasks", "doc_refs", "TEXT")
    ensure_column("tasks", "last_verified_commit", "TEXT")
    ensure_column("tasks", "uid", "TEXT")
    ensure_column("tasks", "migration_epoch", "INTEGER DEFAULT 0")
    ensure_column("tasks", "locked_by_migration", "INTEGER DEFAULT 0")

    prior_story_slugs: dict[str, str] = {}
    prior_story_state: dict[str, dict] = {}
    prior_task_state: dict[tuple, dict] = {}

    if not force:
        try:
            for row in cur.execute(
                "SELECT story_slug, story_key, status, completed_tasks, total_tasks, last_run, updated_at, created_at FROM stories"
            ):
                story_slug = row["story_slug"]
                story_key = row["story_key"]
                if story_key:
                    prior_story_slugs[story_key] = story_slug
                prior_story_state[story_slug] = {
                    "status": row["status"] or "pending",
                    "completed_tasks": int(row["completed_tasks"] or 0),
                    "total_tasks": int(row["total_tasks"] or 0),
                    "last_run": row["last_run"],
                    "updated_at": row["updated_at"],
                    "created_at": row["created_at"],
                }
        except sqlite3.OperationalError:
            pass

        uid_state: dict[str, dict] = {}
        try:
            for row in cur.execute(
                """
                SELECT story_slug, position, task_id, status, started_at, completed_at, last_run,
                       status_reason, evidence_ptr, doc_refs, last_verified_commit,
                       uid, migration_epoch, locked_by_migration, locked_by,
                       reopened_by_migration_at, reopened_by_migration
                  FROM tasks
                """
            ):
                base = {
                    "status": row["status"] or "pending",
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "last_run": row["last_run"],
                    "status_reason": row["status_reason"],
                    "evidence_ptr": row["evidence_ptr"],
                    "doc_refs": row["doc_refs"],
                    "last_verified_commit": row["last_verified_commit"],
                    "uid": row["uid"],
                    "migration_epoch": int(row["migration_epoch"] or 0),
                    "locked_by_migration": int(row["locked_by_migration"] or 0),
                    "locked_by": row["locked_by"],
                    "reopened_by_migration_at": row["reopened_by_migration_at"],
                    "reopened_by_migration": int(row["reopened_by_migration"] or 0),
                }
                prior_task_state[("pos", row["story_slug"], row["position"])] = base
                task_id = (row["task_id"] or "").strip().lower()
                if task_id:
                    prior_task_state[("id", row["story_slug"], task_id)] = base
                if row["uid"]:
                    uid_state[row["uid"]] = base
        except sqlite3.OperationalError:
            uid_state = {}

        try:
            for row in cur.execute("SELECT old_uid, new_uid FROM task_id_map"):
                old_uid = (row["old_uid"] or "").strip()
                new_uid = (row["new_uid"] or "").strip()
                if old_uid and new_uid and old_uid in uid_state and new_uid not in uid_state:
                    uid_state[new_uid] = uid_state[old_uid]
        except sqlite3.OperationalError:
            pass

        for uid_key, payload in uid_state.items():
            prior_task_state[("uid", uid_key)] = payload

    cur.execute("DELETE FROM tasks")
    cur.execute("DELETE FROM stories")
    cur.execute("DELETE FROM epics")

    used_story_slugs = set(prior_story_slugs.values())
    used_story_slugs.discard("")

    def assign_story_slug(preferred: str, story_key: str) -> str:
        if not preferred:
            preferred = "story"
        slug = slugify(preferred)
        if story_key in prior_story_slugs:
            return prior_story_slugs[story_key]
        base = slug or "story"
        candidate = base
        i = 2
        while candidate in used_story_slugs:
            candidate = f"{base}-{i}"
            i += 1
        used_story_slugs.add(candidate)
        return candidate

    epics_inserted = {}
    story_count = 0
    task_count = 0
    restored_stories = 0
    restored_tasks = 0

    for sequence, (story_key, info) in enumerate(grouped.items(), start=1):
        tasks = info["tasks"]
        if not tasks:
            continue
        story_id = info["story_id"]
        story_title = info["story_title"]
        epic_id = info["epic_id"]
        epic_title = info["epic_title"]

        preferred_slug_source = story_id or story_title or epic_id or f"story-{sequence}"
        story_slug = assign_story_slug(preferred_slug_source, story_key)
        restored = story_slug in prior_story_state
        if restored:
            restored_stories += 1

        epic_key = (epic_id or epic_title or "").strip()
        if not epic_key:
            epic_key = None
        else:
            epic_slug = slugify(epic_key)
            if epic_key not in epics_inserted:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO epics(epic_key, epic_id, title, slug, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                """,
                    (
                        epic_key,
                        epic_id or None,
                        epic_title or None,
                        epic_slug,
                        generated_at,
                        generated_at,
                    ),
                )
                epics_inserted[epic_key] = True

        completed_tasks = 0
        story_status = "pending"
        story_total = len(tasks)

        for position, task in enumerate(tasks):
            task_id = (task.get("id") or "").strip()
            description = (task.get("description") or "").strip()
            estimate = (task.get("estimate") or "").strip()
            assignees = task.get("assignees") or []
            tags = task.get("tags") or []
            acceptance = task.get("acceptance_criteria") or []
            dependencies = task.get("dependencies") or []

            key_id = ("id", story_slug, task_id.lower()) if task_id else None
            key_pos = ("pos", story_slug, position)
            task_uid = stable_task_uid(story_slug, task_id, task.get("title"), position)
            restore = None
            if ("uid", task_uid) in prior_task_state and not force:
                restore = prior_task_state[("uid", task_uid)]
            elif key_id and key_id in prior_task_state and not force:
                restore = prior_task_state[key_id]
            elif key_pos in prior_task_state and not force:
                restore = prior_task_state[key_pos]

            status = (restore or {}).get("status") or "pending"
            started_at = (restore or {}).get("started_at")
            completed_at = (restore or {}).get("completed_at")
            last_run = (restore or {}).get("last_run")

            if status in {"complete", "completed-no-changes"}:
                completed_tasks += 1

            if restore:
                restored_tasks += 1

            tags_text = list_to_text(tags)
            dependencies_text = list_to_text(dependencies)
            assignee_text = list_to_text(assignees)
            story_points = as_text(task.get("story_points")) or (estimate if estimate else None)
            document_reference = as_text(task.get("document_reference") or task.get("document_ref"))
            idempotency_text = as_text(task.get("idempotency"))
            rate_limits = as_text(task.get("rate_limits"))
            rbac_text = as_text(task.get("rbac") or task.get("rbac_requirements"))
            messaging_workflows = as_text(task.get("messaging_workflows") or task.get("messaging_and_workflows"))
            performance_targets = as_text(task.get("performance_targets"))
            observability = as_text(task.get("observability"))
            acceptance_text = (
                "\n".join(item.strip() for item in acceptance if item.strip()) if acceptance else None
            )
            if not acceptance_text:
                acceptance_text = as_text(task.get("acceptance_text"))
            endpoints = as_text(task.get("endpoints"))
            sample_create_request = as_text(task.get("sample_create_request") or task.get("sample_request"))
            sample_create_response = as_text(task.get("sample_create_response") or task.get("sample_response"))
            user_story_ref_id = as_text(
                task.get("user_story_ref_id") or task.get("user_story_reference_id") or story_id
            )
            epic_ref_id = as_text(task.get("epic_ref_id") or task.get("epic_reference_id") or epic_id)
            status_reason = (restore or {}).get("status_reason")
            evidence_ptr = (restore or {}).get("evidence_ptr")
            doc_refs = (restore or {}).get("doc_refs")
            last_verified_commit = (restore or {}).get("last_verified_commit")
            locked_by_value = (restore or {}).get("locked_by")
            locked_by_migration = int((restore or {}).get("locked_by_migration") or 0)
            migration_epoch = int((restore or {}).get("migration_epoch") or 0)
            reopened_by_migration_at = (restore or {}).get("reopened_by_migration_at")
            reopened_by_migration = int((restore or {}).get("reopened_by_migration") or 0)

            cur.execute(
                """
                INSERT INTO tasks (
                  story_slug, position, task_id, title, description, estimate,
                  assignees_json, tags_json, acceptance_json, dependencies_json,
                  tags_text, story_points, dependencies_text, assignee_text,
                  document_reference, idempotency, rate_limits, rbac,
                  messaging_workflows, performance_targets, observability,
                  acceptance_text, endpoints, sample_create_request, sample_create_response,
                  user_story_ref_id, epic_ref_id,
                  status, status_reason, evidence_ptr, doc_refs, last_verified_commit,
                  locked_by, locked_by_migration, migration_epoch, reopened_by_migration_at, reopened_by_migration,
                  started_at, completed_at, last_run,
                  story_id, story_title, epic_key, epic_title,
                  uid, updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    story_slug,
                    position,
                    task_id or None,
                    (task.get("title") or "").strip() or None,
                    description or None,
                    estimate or None,
                    json.dumps(assignees, ensure_ascii=False),
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(acceptance, ensure_ascii=False),
                    json.dumps(dependencies, ensure_ascii=False),
                    tags_text,
                    story_points,
                    dependencies_text,
                    assignee_text,
                    document_reference,
                    idempotency_text,
                    rate_limits,
                    rbac_text,
                    messaging_workflows,
                    performance_targets,
                    observability,
                    acceptance_text,
                    endpoints,
                    sample_create_request,
                    sample_create_response,
                    user_story_ref_id,
                    epic_ref_id,
                    status,
                    status_reason,
                    evidence_ptr,
                    doc_refs,
                    last_verified_commit,
                    locked_by_value,
                    locked_by_migration,
                    migration_epoch,
                    reopened_by_migration_at,
                    reopened_by_migration,
                    started_at,
                    completed_at,
                    last_run,
                    story_id or None,
                    story_title or None,
                    epic_key,
                    epic_title or None,
                    task_uid,
                    generated_at,
                    generated_at,
                ),
            )

        if completed_tasks >= story_total and story_total > 0:
            story_status = "complete"
        elif completed_tasks > 0:
            story_status = "in-progress"
        else:
            story_status = "pending"

        if restored and not force:
            state = prior_story_state.get(story_slug, {})
            if state:
                story_status = state.get("status") or story_status
                restored_completed = int(state.get("completed_tasks") or completed_tasks)
                completed_tasks = max(completed_tasks, restored_completed)
                story_total = state.get("total_tasks") or story_total

        cur.execute(
            """
            INSERT OR REPLACE INTO stories (
              story_slug, story_key, story_id, story_title,
              epic_key, epic_title, sequence, status,
              completed_tasks, total_tasks, last_run,
              updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                story_slug,
                story_key,
                story_id or None,
                story_title or None,
                epic_key,
                epic_title or None,
                sequence,
                story_status,
                completed_tasks,
                story_total,
                (prior_story_state.get(story_slug) or {}).get("last_run")
                if restored and not force
                else None,
                generated_at,
                (prior_story_state.get(story_slug) or {}).get("created_at", generated_at)
                if restored and not force
                else generated_at,
            ),
        )

        story_count += 1
        task_count += story_total

    cur.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("generated_at", generated_at))
    cur.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("source", str(tasks_json_path)))

    conn.commit()
    conn.close()

    print(f"STORIES {story_count}")
    print(f"TASKS {task_count}")
    print(f"RESTORED_STORIES {restored_stories}")
    print(f"RESTORED_TASKS {restored_tasks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
