#!/usr/bin/env python3
"""Incrementally upsert a story and its tasks into tasks.db."""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            return [text]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [text]
    return [str(value).strip()]


def _join(values: Iterable[str]) -> str:
    cleaned = [item for item in (v.strip() for v in values) if item]
    return ", ".join(cleaned)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return _join([str(item) for item in value])
    return str(value).strip()


def _json_dump(value: Any) -> str:
    if value is None:
        return "[]"
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    coerced = _as_list(value)
    return json.dumps(coerced, ensure_ascii=False)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "item"

_STATUS_RANK = {
    "pending": 0,
    "on-hold": 1,
    "in-progress": 2,
    "blocked": 3,
    "complete": 4,
}


def _normalize_status(value: Any) -> str:
    status = _text(value).lower()
    if not status:
        return ""
    status = status.replace("_", "-")
    synonyms = {
        "completed": "complete",
        "done": "complete",
        "finished": "complete",
        "complete": "complete",
        "in progress": "in-progress",
        "progress": "in-progress",
        "started": "in-progress",
        "on hold": "on-hold",
        "hold": "on-hold",
        "paused": "on-hold",
        "deferred": "on-hold",
        "waiting": "on-hold",
        "blocked": "blocked",
        "blocker": "blocked",
        "todo": "pending",
        "to-do": "pending",
        "backlog": "pending",
        "ready": "pending",
    }
    normalized = synonyms.get(status, status)
    return normalized if normalized in _STATUS_RANK else ""


def _merge_status(existing: str, incoming: str) -> str:
    if incoming and not existing:
        return incoming
    if existing and not incoming:
        return existing
    if existing and incoming:
        if _STATUS_RANK[incoming] >= _STATUS_RANK[existing]:
            return incoming
        return existing
    return "pending"


def ensure_schema(cur: sqlite3.Cursor) -> None:
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
          refined INTEGER DEFAULT 0,
          refined_at TEXT,
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
          duration_seconds INTEGER,
          apply_status TEXT,
          changes_applied INTEGER,
          notes_json TEXT,
          written_json TEXT,
          patched_json TEXT,
          commands_json TEXT,
          occurred_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
        """
    )

    # Optional columns that may appear in existing databases
    optional_story_columns = {
        "completed_tasks": "INTEGER",
        "total_tasks": "INTEGER",
        "status": "TEXT DEFAULT 'pending'",
        "last_run": "TEXT",
        "epic_title": "TEXT",
    }
    cur.execute("PRAGMA table_info(stories)")
    story_columns = {row[1] for row in cur.fetchall()}
    for column, definition in optional_story_columns.items():
        if column not in story_columns:
            cur.execute(f"ALTER TABLE stories ADD COLUMN {column} {definition}")

    optional_task_columns = {
        "tags_text": "TEXT",
        "story_points": "TEXT",
        "dependencies_text": "TEXT",
        "assignee_text": "TEXT",
        "document_reference": "TEXT",
        "idempotency": "TEXT",
        "rate_limits": "TEXT",
        "rbac": "TEXT",
        "messaging_workflows": "TEXT",
        "performance_targets": "TEXT",
        "observability": "TEXT",
        "acceptance_text": "TEXT",
        "endpoints": "TEXT",
        "sample_create_request": "TEXT",
        "sample_create_response": "TEXT",
        "user_story_ref_id": "TEXT",
        "epic_ref_id": "TEXT",
        "refined": "INTEGER DEFAULT 0",
        "refined_at": "TEXT",
        "last_log_path": "TEXT",
        "last_prompt_path": "TEXT",
        "last_output_path": "TEXT",
        "last_attempts": "INTEGER",
        "last_tokens_total": "INTEGER",
        "last_duration_seconds": "INTEGER",
        "last_apply_status": "TEXT",
        "last_changes_applied": "INTEGER",
        "last_notes_json": "TEXT",
        "last_written_json": "TEXT",
        "last_patched_json": "TEXT",
        "last_commands_json": "TEXT",
        "last_progress_at": "TEXT",
        "last_progress_run": "TEXT",
    }
    cur.execute("PRAGMA table_info(tasks)")
    task_columns = {row[1] for row in cur.fetchall()}
    for column, definition in optional_task_columns.items():
        if column not in task_columns:
            cur.execute(f"ALTER TABLE tasks ADD COLUMN {column} {definition}")


def fetch_task_state(cur: sqlite3.Cursor, *, task_id: Optional[str], story_slug: str, position: int) -> Optional[Tuple]:
    if task_id:
        row = cur.execute(
            "SELECT status, started_at, completed_at, last_run, refined, refined_at FROM tasks WHERE LOWER(task_id) = ?",
            (task_id.lower(),),
        ).fetchone()
        if row:
            return row
    return cur.execute(
        "SELECT status, started_at, completed_at, last_run, refined, refined_at FROM tasks WHERE story_slug = ? AND position = ?",
        (story_slug, position),
    ).fetchone()


def delete_conflicts(cur: sqlite3.Cursor, *, task_id: Optional[str], story_slug: str, position: int) -> None:
    if task_id:
        cur.execute("DELETE FROM tasks WHERE LOWER(task_id) = ?", (task_id.lower(),))
    cur.execute("DELETE FROM tasks WHERE story_slug = ? AND position = ?", (story_slug, position))


def upsert_story(db_path: Path, story_path: Path, story_slug: str) -> None:
    payload = json.loads(story_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") or []
    story_id = _text(payload.get("story_id")) or None
    story_title = _text(payload.get("story_title")) or None
    epic_id = _text(payload.get("epic_id")) or None
    epic_title = _text(payload.get("epic_title")) or None

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")

    ensure_schema(cur)

    epic_key = (epic_id or epic_title or "").strip() or None
    if epic_key:
        cur.execute(
            """
            INSERT OR REPLACE INTO epics(epic_key, epic_id, title, slug, created_at, updated_at)
            VALUES(?, ?, ?, ?, COALESCE((SELECT created_at FROM epics WHERE epic_key = ?), ?), ?)
            """,
            (
                epic_key,
                epic_id or None,
                epic_title or None,
                _slugify(epic_key or ""),
                epic_key,
                now,
                now,
            ),
        )

    story_key = "|".join(
        part for part in (
            story_id or "",
            story_title or "",
            epic_id or "",
            epic_title or "",
        )
    )

    existing_story = cur.execute(
        "SELECT sequence, status, completed_tasks, total_tasks, last_run, created_at FROM stories WHERE story_slug = ?",
        (story_slug,),
    ).fetchone()
    if existing_story:
        sequence, status, completed_tasks, total_tasks, last_run, created_at = existing_story
        sequence = sequence or 0
        status = _normalize_status(status) or "pending"
        completed_tasks = int(completed_tasks or 0)
        total_tasks = int(total_tasks or 0)
        last_run = last_run
        created_at = created_at or now
    else:
        row = cur.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM stories").fetchone()
        sequence = (row[0] if row and row[0] is not None else 0) or 1
        status = "pending"
        completed_tasks = 0
        total_tasks = 0
        last_run = None
        created_at = now

    cur.execute(
        """
        INSERT OR REPLACE INTO stories (
          story_slug, story_key, story_id, story_title, epic_key, epic_title,
          sequence, status, completed_tasks, total_tasks, last_run, updated_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            story_slug,
            story_key or None,
            story_id,
            story_title,
            epic_key,
            epic_title,
            sequence,
            status,
            completed_tasks,
            len(tasks),
            last_run,
            now,
            created_at,
        ),
    )

    completed_count = 0

    total_tasks = len(tasks)

    for position, task in enumerate(tasks):
        task_id_value = _text(task.get("id") or task.get("task_id")) or None
        if task_id_value:
            task_id_value = task_id_value.upper()

        state = fetch_task_state(cur, task_id=task_id_value, story_slug=story_slug, position=position)
        delete_conflicts(cur, task_id=task_id_value, story_slug=story_slug, position=position)

        existing_status = _normalize_status(state[0] if state else "")
        incoming_status = _normalize_status(
            task.get("status")
            or task.get("state")
            or task.get("progress")
            or task.get("task_status")
        )
        status_value = _merge_status(existing_status, incoming_status)
        started_at = state[1] if state and state[1] else (_text(task.get("started_at")) or None)
        completed_at = state[2] if state and state[2] else (_text(task.get("completed_at")) or None)
        last_run_value = state[3] if state and state[3] else (_text(task.get("last_run")) or None)
        refined_flag = int(state[4] or 0) if state else int(task.get("refined") or 0)
        refined_at = state[5] if state else task.get("refined_at")
        if int(task.get("refined") or 0):
            refined_flag = 1
            refined_at = task.get("refined_at") or refined_at or now

        if status_value == "complete":
            completed_count += 1

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
              refined, refined_at, status, started_at, completed_at, last_run,
              story_id, story_title, epic_key, epic_title, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_slug,
                position,
                task_id_value,
                _text(task.get("title")) or None,
                _text(task.get("description")) or None,
                _text(task.get("estimate")) or None,
                _json_dump(task.get("assignees")),
                _json_dump(task.get("tags")),
                _json_dump(task.get("acceptance_criteria")),
                _json_dump(task.get("dependencies")),
                _text(task.get("tags_text")) or None,
                _text(task.get("story_points")) or None,
                _text(task.get("dependencies_text")) or None,
                _text(task.get("assignee_text")) or None,
                _text(task.get("document_reference") or task.get("document_references")) or None,
                _text(task.get("idempotency")) or None,
                _text(task.get("rate_limits")) or None,
                _text(task.get("rbac") or task.get("policy")) or None,
                _text(task.get("messaging_workflows")) or None,
                _text(task.get("performance_targets")) or None,
                _text(task.get("observability")) or None,
                _text(task.get("acceptance_text")) or None,
                _text(task.get("endpoints")) or None,
                _text(task.get("sample_create_request") or task.get("sample_request")) or None,
                _text(task.get("sample_create_response") or task.get("sample_response")) or None,
                _text(task.get("user_story_ref_id")) or None,
                _text(task.get("epic_ref_id")) or None,
                refined_flag,
                refined_at,
                status_value,
                started_at,
                completed_at,
                last_run_value,
                _text(task.get("story_id") or story_id) or None,
                _text(task.get("story_title") or story_title) or None,
                epic_key,
                _text(task.get("epic_title") or epic_title) or None,
                now,
                now,
            ),
        )

    story_status = "pending"
    if completed_count >= len(tasks) and len(tasks) > 0:
        story_status = "complete"
    elif completed_count > 0:
        story_status = "in-progress"

    if existing_story:
        # Preserve manual overrides where applicable
        preserved_status = _normalize_status(existing_story[1])
        if preserved_status:
            story_status = preserved_status
        preserved_completed = int(existing_story[2] or 0)
        if preserved_completed > completed_count:
            completed_count = preserved_completed

    if completed_count > total_tasks:
        completed_count = total_tasks

    if total_tasks == 0:
        cur.execute("DELETE FROM tasks WHERE story_slug = ?", (story_slug,))
    else:
        cur.execute("DELETE FROM tasks WHERE story_slug = ? AND position >= ?", (story_slug, total_tasks))

    cur.execute(
        """
        UPDATE stories
           SET status = ?,
               completed_tasks = ?,
               total_tasks = ?,
               updated_at = ?
         WHERE story_slug = ?
        """,
        (story_status, completed_count, total_tasks, now, story_slug),
    )

    conn.commit()
    conn.close()


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: upsert_story_into_db.py <tasks.db> <story.json> <story_slug>")

    db_path = Path(sys.argv[1])
    story_path = Path(sys.argv[2])
    story_slug = sys.argv[3]

    if not story_path.exists():
        raise SystemExit(f"Story JSON not found: {story_path}")

    upsert_story(db_path, story_path, story_slug)


if __name__ == "__main__":
    main()
