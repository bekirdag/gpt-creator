#!/usr/bin/env python3
"""Write tasks payload into the create-tasks SQLite schema."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def read_payload(path: Path) -> Dict[str, List[Dict[str, object]]]:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "item"


def list_to_text(values: Iterable[object]) -> str:
    if not values:
        return ""
    parts = [str(item).strip() for item in values if str(item).strip()]
    return ", ".join(parts)


def as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return list_to_text(value)
    return str(value).strip()


def ensure_table(cur: sqlite3.Cursor) -> None:
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
          started_at TEXT,
          completed_at TEXT,
          last_run TEXT,
          story_id TEXT,
          story_title TEXT,
          epic_key TEXT,
          epic_title TEXT,
          updated_at TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(story_slug, position),
          FOREIGN KEY(story_slug) REFERENCES stories(story_slug)
        )
        """
    )


def ensure_column(cur: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    if any(row[1] == column for row in cur.fetchall()):
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def sync_optional_columns(cur: sqlite3.Cursor) -> None:
    ensure_column(cur, "stories", "completed_tasks", "INTEGER")
    ensure_column(cur, "stories", "total_tasks", "INTEGER")
    ensure_column(cur, "stories", "status", "TEXT DEFAULT 'pending'")
    ensure_column(cur, "stories", "last_run", "TEXT")
    ensure_column(cur, "stories", "epic_title", "TEXT")

    cols = [
        ("story_id", "TEXT"),
        ("story_title", "TEXT"),
        ("epic_key", "TEXT"),
        ("epic_title", "TEXT"),
        ("status", "TEXT DEFAULT 'pending'"),
        ("started_at", "TEXT"),
        ("completed_at", "TEXT"),
        ("last_run", "TEXT"),
        ("tags_text", "TEXT"),
        ("story_points", "TEXT"),
        ("dependencies_text", "TEXT"),
        ("assignee_text", "TEXT"),
        ("document_reference", "TEXT"),
        ("idempotency", "TEXT"),
        ("rate_limits", "TEXT"),
        ("rbac", "TEXT"),
        ("messaging_workflows", "TEXT"),
        ("performance_targets", "TEXT"),
        ("observability", "TEXT"),
        ("acceptance_text", "TEXT"),
        ("endpoints", "TEXT"),
        ("sample_create_request", "TEXT"),
        ("sample_create_response", "TEXT"),
        ("user_story_ref_id", "TEXT"),
        ("epic_ref_id", "TEXT"),
    ]
    for column, definition in cols:
        ensure_column(cur, "tasks", column, definition)


def load_prior_state(cur: sqlite3.Cursor, force: bool) -> Tuple[Dict[str, str], Dict[str, Dict[str, object]], Dict[Tuple[str, str], Dict[str, object]]]:
    prior_story_slugs: Dict[str, str] = {}
    prior_story_state: Dict[str, Dict[str, object]] = {}
    prior_task_state: Dict[Tuple[str, str], Dict[str, object]] = {}

    if force:
        return prior_story_slugs, prior_story_state, prior_task_state

    try:
        for row in cur.execute(
            "SELECT story_slug, story_key, status, completed_tasks, total_tasks, last_run, updated_at, created_at FROM stories"
        ):
            story_slug = row[0]
            story_key = row[1] or ""
            if story_key:
                prior_story_slugs[story_key] = story_slug
            prior_story_state[story_slug] = {
                "status": row[2] or "pending",
                "completed_tasks": int(row[3] or 0),
                "total_tasks": int(row[4] or 0),
                "last_run": row[5],
                "updated_at": row[6],
                "created_at": row[7],
            }
    except sqlite3.OperationalError:
        pass

    try:
        for row in cur.execute(
            "SELECT story_slug, position, task_id, status, started_at, completed_at, last_run FROM tasks"
        ):
            story_slug, position, task_id, status, started_at, completed_at, last_run = row
            base = {
                "status": status or "pending",
                "started_at": started_at,
                "completed_at": completed_at,
                "last_run": last_run,
            }
            prior_task_state[("pos", story_slug, str(position))] = base
            tid = (task_id or "").strip().lower()
            if tid:
                prior_task_state[("id", story_slug, tid)] = base
    except sqlite3.OperationalError:
        pass

    return prior_story_slugs, prior_story_state, prior_task_state


def assign_story_slug(prior_story_slugs: Dict[str, str], used_slugs: set, preferred: str, story_key: str) -> str:
    if story_key in prior_story_slugs:
        return prior_story_slugs[story_key]
    base = slugify(preferred or story_key or "story")
    slug = base
    idx = 2
    while slug in used_slugs:
        slug = f"{base}-{idx}"
        idx += 1
    used_slugs.add(slug)
    return slug


def build_database(tasks: List[Dict[str, object]], db_path: Path, force: bool, source_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")

    ensure_table(cur)
    sync_optional_columns(cur)

    prior_story_slugs, prior_story_state, prior_task_state = load_prior_state(cur, force)

    cur.execute("DELETE FROM tasks")
    cur.execute("DELETE FROM stories")
    cur.execute("DELETE FROM epics")

    grouped: "OrderedDict[str, Dict[str, object]]" = OrderedDict()
    for task in tasks:
        story_key = "|".join(
            [
                (str(task.get("story_id")) or "").strip(),
                (str(task.get("story_title")) or "").strip(),
                (str(task.get("epic_id")) or "").strip(),
                (str(task.get("epic_title")) or "").strip(),
            ]
        )
        grouped.setdefault(
            story_key,
            {
                "story_id": (str(task.get("story_id")) or "").strip(),
                "story_title": (str(task.get("story_title")) or "").strip(),
                "epic_id": (str(task.get("epic_id")) or "").strip(),
                "epic_title": (str(task.get("epic_title")) or "").strip(),
                "tasks": [],
            },
        )["tasks"].append(task)

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    used_slugs = set(prior_story_slugs.values())
    used_slugs.discard("")

    story_count = 0
    task_count = 0

    for sequence, (story_key, info) in enumerate(grouped.items(), start=1):
        tasks_list = info["tasks"]
        if not tasks_list:
            continue
        story_id = info["story_id"]
        story_title = info["story_title"]
        epic_id = info["epic_id"]
        epic_title = info["epic_title"]

        preferred_slug_source = story_id or story_title or epic_id or f"story-{sequence}"
        story_slug = assign_story_slug(prior_story_slugs, used_slugs, preferred_slug_source, story_key)
        restored = story_slug in prior_story_state and not force
        if restored:
            restored_state = prior_story_state[story_slug]
        else:
            restored_state = {}

        epic_key = (epic_id or epic_title or "").strip() or None
        if epic_key:
            epic_slug = slugify(epic_key)
            cur.execute(
                """
                INSERT OR REPLACE INTO epics(epic_key, epic_id, title, slug, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (epic_key, epic_id or None, epic_title or None, epic_slug, generated_at, generated_at),
            )

        completed_tasks = 0
        story_total = len(tasks_list)

        for position, task in enumerate(tasks_list):
            task_id = (str(task.get("id") or task.get("task_id")) or "").strip()
            key_id = ("id", story_slug, task_id.lower()) if task_id else None
            key_pos = ("pos", story_slug, str(position))
            restore = None
            if not force:
                if key_id and key_id in prior_task_state:
                    restore = prior_task_state[key_id]
                elif key_pos in prior_task_state:
                    restore = prior_task_state[key_pos]

            status = (restore or {}).get("status") or "pending"
            started_at = (restore or {}).get("started_at")
            completed_at = (restore or {}).get("completed_at")
            last_run = (restore or {}).get("last_run")
            if status == "complete":
                completed_tasks += 1

            cur.execute(
                """
                INSERT INTO tasks (
                  story_slug, position, task_id, title, description, estimate,
                  assignees_json, tags_json, acceptance_json, dependencies_json,
                  tags_text, story_points, dependencies_text, assignee_text,
                  document_reference, idempotency, rate_limits, rbac,
                  messaging_workflows, performance_targets, observability,
                  acceptance_text, endpoints, sample_create_request,
                  sample_create_response, user_story_ref_id, epic_ref_id,
                  status, started_at, completed_at, last_run,
                  story_id, story_title, epic_key, epic_title,
                  updated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    story_slug,
                    position,
                    task_id or None,
                    as_text(task.get("title")) or None,
                    as_text(task.get("description")) or None,
                    as_text(task.get("estimate")) or None,
                    json.dumps(task.get("assignees") or [], ensure_ascii=False),
                    json.dumps(task.get("tags") or [], ensure_ascii=False),
                    json.dumps(task.get("acceptance_criteria") or [], ensure_ascii=False),
                    json.dumps(task.get("dependencies") or [], ensure_ascii=False),
                    as_text(task.get("tags_text")) or None,
                    as_text(task.get("story_points")) or None,
                    as_text(task.get("dependencies_text")) or None,
                    as_text(task.get("assignee_text")) or None,
                    as_text(task.get("document_reference")) or None,
                    as_text(task.get("idempotency")) or None,
                    as_text(task.get("rate_limits")) or None,
                    as_text(task.get("rbac")) or None,
                    as_text(task.get("messaging_workflows")) or None,
                    as_text(task.get("performance_targets")) or None,
                    as_text(task.get("observability")) or None,
                    as_text(task.get("acceptance_text")) or None,
                    as_text(task.get("endpoints")) or None,
                    as_text(task.get("sample_create_request")) or None,
                    as_text(task.get("sample_create_response")) or None,
                    as_text(task.get("user_story_ref_id")) or None,
                    as_text(task.get("epic_ref_id")) or None,
                    status,
                    started_at,
                    completed_at,
                    last_run,
                    as_text(task.get("story_id") or story_id) or None,
                    as_text(task.get("story_title") or story_title) or None,
                    epic_key,
                    as_text(task.get("epic_title") or epic_title) or None,
                    generated_at,
                    generated_at,
                ),
            )

        story_status = "pending"
        if completed_tasks >= story_total and story_total > 0:
            story_status = "complete"
        elif completed_tasks > 0:
            story_status = "in-progress"

        if restored and not force:
            state = prior_story_state.get(story_slug, {})
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
                (prior_story_state.get(story_slug) or {}).get("last_run") if restored and not force else None,
                generated_at,
                (prior_story_state.get(story_slug) or {}).get("created_at", generated_at)
                if restored and not force
                else generated_at,
            ),
        )

        story_count += 1
        task_count += story_total

    cur.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        ("generated_at", generated_at),
    )
    cur.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        ("source", str(source_path.resolve())),
    )

    conn.commit()
    conn.close()


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: to_sqlite.py <payload.json> <db-path> <force-flag>")

    payload_path = Path(sys.argv[1])
    db_path = Path(sys.argv[2])
    force_flag = sys.argv[3] == "1"

    payload = read_payload(payload_path)
    tasks = payload.get("tasks") or []
    build_database(tasks, db_path, force_flag, payload_path)


if __name__ == "__main__":
    main()
