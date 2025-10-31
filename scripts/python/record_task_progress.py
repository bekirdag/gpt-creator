import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

from task_binder import update_after_progress as binder_update_after_progress

TERMINAL_LOCK_STATUSES = {
    "complete",
    "completed",
    "completed-no-changes",
    "blocked-budget",
    "blocked-quota",
    "blocked-merge-conflict",
    "blocked-schema-drift",
    "blocked-schema-guard-error",
    "skipped-already-complete",
}


def _is_blocked_dependency(status: Optional[str]) -> bool:
    return (status or "").strip().lower().startswith("blocked-dependency(")


def parse_int(value: Optional[str]) -> Optional[int]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def parse_bool(value: Optional[str]) -> int:
    text = (value or "").strip().lower()
    return 1 if text in {"1", "true", "yes", "y", "on"} else 0


def parse_points(value: Optional[str]) -> float:
    text = (value or "").strip()
    if not text:
        return 0.0
    normalized = text.lower().replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return 0.0
    try:
        points = float(match.group(0))
    except (TypeError, ValueError):
        return 0.0
    return points if points > 0 else 0.0


def as_json(text: str) -> Optional[str]:
    items = [line.strip() for line in text.splitlines() if line.strip()]
    return json.dumps(items, ensure_ascii=False) if items else None


def split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def ensure_column(cur: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    if not any(row["name"] == column for row in cur.fetchall()):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def record_task_progress(
    *,
    db_path: Path,
    story_slug: str,
    position: str,
    run_stamp: str,
    status: str,
    log_path: str,
    prompt_path: str,
    output_path: str,
    attempts: str,
    tokens_total: str,
    tokens_estimate: str,
    llm_prompt_tokens: str,
    llm_completion_tokens: str,
    duration_seconds: str,
    apply_status: str,
    changes_applied: str,
    notes_text: str,
    written_text: str,
    patched_text: str,
    commands_text: str,
    observation_hash: str,
    occurred_at: str,
    stage_tokens_retrieve: str,
    stage_tokens_plan: str,
    stage_tokens_patch: str,
    stage_tokens_verify: str,
    story_points_raw: str,
) -> None:
    position_int = int(position)
    attempts_int = parse_int(attempts) or 0
    tokens_int = parse_int(tokens_total)
    tokens_estimate_int = parse_int(tokens_estimate) or 0
    llm_prompt_tokens_int = parse_int(llm_prompt_tokens) or 0
    llm_completion_tokens_int = parse_int(llm_completion_tokens) or 0
    duration_int = parse_int(duration_seconds)
    changes_int = parse_bool(changes_applied)
    run_stamp = (run_stamp or "manual").strip() or "manual"
    status_value = (status or "").strip()
    log_path = (log_path or "").strip() or None
    prompt_path = (prompt_path or "").strip() or None
    output_path = (output_path or "").strip() or None
    apply_status = (apply_status or "").strip() or None
    notes_text = notes_text or ""
    written_text = written_text or ""
    patched_text = patched_text or ""
    commands_text = commands_text or ""
    observation_hash = (observation_hash or "").strip()

    notes_json = as_json(notes_text)
    written_json = as_json(written_text)
    patched_json = as_json(patched_text)
    commands_json = as_json(commands_text)

    timestamp = (occurred_at or "").strip()
    if not timestamp:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tokens_retrieve_int = parse_int(stage_tokens_retrieve) or 0
    tokens_plan_int = parse_int(stage_tokens_plan) or 0
    tokens_patch_int = parse_int(stage_tokens_patch) or 0
    tokens_verify_int = parse_int(stage_tokens_verify) or 0
    tokens_retrieve_int = max(tokens_retrieve_int, 0)
    tokens_plan_int = max(tokens_plan_int, 0)
    tokens_patch_int = max(tokens_patch_int, 0)
    tokens_verify_int = max(tokens_verify_int, 0)
    tokens_stage_total = tokens_retrieve_int + tokens_plan_int + tokens_patch_int + tokens_verify_int
    story_points_value = parse_points(story_points_raw)
    tokens_per_sp_value = tokens_stage_total / story_points_value if story_points_value > 0 else 0.0
    hotspot_phase = ""
    if tokens_stage_total > 0:
        stage_pairs = [
            ("retrieve", tokens_retrieve_int),
            ("plan", tokens_plan_int),
            ("patch", tokens_patch_int),
            ("verify", tokens_verify_int),
        ]
        max_stage = max(stage_pairs, key=lambda item: item[1])
        if max_stage[1] > 0:
            hotspot_phase = max_stage[0]

    if tokens_int is None:
        tokens_int = tokens_stage_total

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

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
          tokens_retrieve INTEGER,
          tokens_plan INTEGER,
          tokens_patch INTEGER,
          tokens_verify INTEGER,
          tokens_per_sp REAL,
          story_points REAL,
          hotspot_phase TEXT,
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

    for column, definition in (
        ("tokens_retrieve", "INTEGER"),
        ("tokens_plan", "INTEGER"),
        ("tokens_patch", "INTEGER"),
        ("tokens_verify", "INTEGER"),
        ("tokens_per_sp", "REAL"),
        ("story_points", "REAL"),
        ("hotspot_phase", "TEXT"),
        ("tokens_prompt_estimate", "INTEGER"),
        ("llm_prompt_tokens", "INTEGER"),
        ("llm_completion_tokens", "INTEGER"),
    ):
        ensure_column(cur, "task_progress", column, definition)

    for column, definition in (
        ("last_log_path", "TEXT"),
        ("last_prompt_path", "TEXT"),
        ("last_output_path", "TEXT"),
        ("last_attempts", "INTEGER"),
        ("last_tokens_total", "INTEGER"),
        ("last_prompt_tokens_estimate", "INTEGER"),
        ("last_llm_prompt_tokens", "INTEGER"),
        ("last_llm_completion_tokens", "INTEGER"),
        ("last_duration_seconds", "INTEGER"),
        ("last_apply_status", "TEXT"),
        ("last_changes_applied", "INTEGER"),
        ("last_notes_json", "TEXT"),
        ("last_written_json", "TEXT"),
        ("last_patched_json", "TEXT"),
        ("last_commands_json", "TEXT"),
        ("last_progress_at", "TEXT"),
        ("last_progress_run", "TEXT"),
        ("status_reason", "TEXT"),
        ("locked_by_migration", "INTEGER DEFAULT 0"),
        ("migration_epoch", "INTEGER DEFAULT 0"),
        ("locked_by", "TEXT"),
        ("doc_refs", "TEXT"),
        ("last_verified_commit", "TEXT"),
        ("last_tokens_retrieve", "INTEGER"),
        ("last_tokens_plan", "INTEGER"),
        ("last_tokens_patch", "INTEGER"),
        ("last_tokens_verify", "INTEGER"),
        ("last_tokens_per_sp", "REAL"),
        ("last_story_points", "REAL"),
        ("last_hotspot_phase", "TEXT"),
    ):
        ensure_column(cur, "tasks", column, definition)

    task_row = cur.execute(
        """
        SELECT id,
               status,
               locked_by_migration,
               status_reason,
               task_id,
               story_slug,
               epic_key
          FROM tasks
         WHERE story_slug = ? AND position = ?
        """,
        (story_slug, position_int),
    ).fetchone()
    task_id = task_row["id"] if task_row else None
    task_ref = str(task_id) if task_id is not None else f"{story_slug}:{position_int}"
    existing_status = (task_row["status"] or "").strip() if task_row else ""
    existing_status_lower = existing_status.lower()
    locked_by_migration = int(task_row["locked_by_migration"] or 0) if task_row else 0
    status_lower = status_value.lower()
    apply_status_lower = (apply_status or "").strip().lower() if apply_status else ""
    status_reason_update = None

    if apply_status_lower in {"empty-apply", "invalid-json", "no-output"}:
        if locked_by_migration and (
            existing_status_lower in TERMINAL_LOCK_STATUSES or _is_blocked_dependency(existing_status_lower)
        ):
            status_value = existing_status
            status_lower = existing_status_lower
        else:
            status_value = "apply-failed-migration-context"
            status_lower = status_value
        status_reason_update = apply_status_lower

    if locked_by_migration and (
        existing_status_lower in TERMINAL_LOCK_STATUSES or _is_blocked_dependency(existing_status_lower)
    ):
        if not status_lower or status_lower in {"skipped-no-changes", "pending"}:
            status_value = existing_status
            status_lower = existing_status_lower

    if status_lower == "blocked-migration-transition":
        status_reason_update = status_reason_update or "migration-epoch-change"

    final_status = status_value or None

    progress_row: Iterable = (
        task_id,
        story_slug,
        position_int,
        run_stamp,
        final_status,
        log_path,
        prompt_path,
        output_path,
        attempts_int,
        tokens_int,
        tokens_estimate_int,
        llm_prompt_tokens_int,
        llm_completion_tokens_int,
        tokens_retrieve_int,
        tokens_plan_int,
        tokens_patch_int,
        tokens_verify_int,
        tokens_per_sp_value,
        story_points_value,
        hotspot_phase,
        duration_int,
        apply_status,
        changes_int,
        notes_json,
        written_json,
        patched_json,
        commands_json,
        timestamp,
        timestamp,
        timestamp,
    )

    cur.execute(
        """
        INSERT INTO task_progress (
          task_id, story_slug, task_position, run_stamp, status, log_path,
          prompt_path, output_path, attempts, tokens_total, tokens_prompt_estimate,
          llm_prompt_tokens, llm_completion_tokens, tokens_retrieve, tokens_plan,
          tokens_patch, tokens_verify, tokens_per_sp, story_points,
          hotspot_phase, duration_seconds, apply_status, changes_applied,
          notes_json, written_json, patched_json, commands_json, occurred_at,
          created_at, updated_at
        )
        VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        progress_row,
    )

    task_updates = []
    params = []

    def set_field(column: str, value) -> None:
        task_updates.append(f"{column} = ?")
        params.append(value)

    set_field("last_log_path", log_path)
    set_field("last_prompt_path", prompt_path)
    set_field("last_output_path", output_path)
    set_field("last_attempts", attempts_int)
    set_field("last_tokens_total", tokens_int)
    set_field("last_prompt_tokens_estimate", tokens_estimate_int)
    set_field("last_llm_prompt_tokens", llm_prompt_tokens_int)
    set_field("last_llm_completion_tokens", llm_completion_tokens_int)
    set_field("last_duration_seconds", duration_int)
    set_field("last_apply_status", apply_status)
    set_field("last_changes_applied", changes_int)
    set_field("last_notes_json", notes_json)
    set_field("last_written_json", written_json)
    set_field("last_patched_json", patched_json)
    set_field("last_commands_json", commands_json)
    set_field("last_progress_at", timestamp)
    set_field("last_progress_run", run_stamp)
    set_field("last_tokens_retrieve", tokens_retrieve_int)
    set_field("last_tokens_plan", tokens_plan_int)
    set_field("last_tokens_patch", tokens_patch_int)
    set_field("last_tokens_verify", tokens_verify_int)
    set_field("last_tokens_per_sp", tokens_per_sp_value)
    set_field("last_story_points", story_points_value)
    set_field("last_hotspot_phase", hotspot_phase)
    set_field("updated_at", timestamp)
    if status_reason_update:
        set_field("status_reason", status_reason_update)

    if task_row:
        cur.execute(
            f"""
            UPDATE tasks
               SET {", ".join(task_updates)}
             WHERE id = ?
            """,
            params + [task_id],
        )

    binder_enabled = os.getenv("GC_BINDER_ENABLED", "").strip().lower() not in {"0", "false", "no", "off"}
    if binder_enabled and task_row:
        project_root = os.getenv("PROJECT_ROOT", "").strip()
        if project_root:
            binder_reopened = False
            if locked_by_migration and status_lower not in TERMINAL_LOCK_STATUSES and not _is_blocked_dependency(status_lower):
                binder_reopened = True
            if status_lower == "blocked-migration-transition":
                binder_reopened = True

            binder_update_after_progress(
                Path(project_root),
                epic_slug=task_row.get("epic_key") or "",
                story_slug=task_row.get("story_slug") or story_slug,
                task_id=task_row.get("task_id") or f"{story_slug}:{position_int}",
                status=final_status or "",
                apply_status=apply_status,
                notes=split_lines(notes_text),
                written_paths=split_lines(written_text),
                patched_paths=split_lines(patched_text),
                tokens_total=tokens_int,
                run_stamp=run_stamp,
                reopened_by_migration=binder_reopened,
            )

    if observation_hash and tokens_int > 0:
        try:
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
            cur.execute(
                """
                INSERT INTO doc_observations(task_id, doc_hash, tokens, first_seen_at)
                VALUES(?, ?, ?, strftime('%s','now'))
                ON CONFLICT(task_id, doc_hash) DO UPDATE SET tokens=excluded.tokens
                """,
                (task_ref, observation_hash, int(tokens_int)),
            )
        except sqlite3.DatabaseError:
            pass

    conn.commit()
    conn.close()


def main() -> int:
    if len(sys.argv) < 28:
        return 1

    db_path = Path(sys.argv[1])
    story_slug = sys.argv[2]
    position = sys.argv[3]
    run_stamp = sys.argv[4]
    status = sys.argv[5]
    log_path = sys.argv[6]
    prompt_path = sys.argv[7]
    output_path = sys.argv[8]
    attempts = sys.argv[9]
    tokens_total = sys.argv[10]
    tokens_estimate = sys.argv[11]
    llm_prompt_tokens = sys.argv[12]
    llm_completion_tokens = sys.argv[13]
    duration_seconds = sys.argv[14]
    apply_status = sys.argv[15]
    changes_applied = sys.argv[16]
    notes_text = sys.argv[17]
    written_text = sys.argv[18]
    patched_text = sys.argv[19]
    commands_text = sys.argv[20]
    observation_hash = sys.argv[21]
    occurred_at = sys.argv[22]
    stage_tokens_retrieve = sys.argv[23]
    stage_tokens_plan = sys.argv[24]
    stage_tokens_patch = sys.argv[25]
    stage_tokens_verify = sys.argv[26]
    story_points_raw = sys.argv[27]

    record_task_progress(
        db_path=db_path,
        story_slug=story_slug,
        position=position,
        run_stamp=run_stamp,
        status=status,
        log_path=log_path,
        prompt_path=prompt_path,
        output_path=output_path,
        attempts=attempts,
        tokens_total=tokens_total,
        tokens_estimate=tokens_estimate,
        llm_prompt_tokens=llm_prompt_tokens,
        llm_completion_tokens=llm_completion_tokens,
        duration_seconds=duration_seconds,
        apply_status=apply_status,
        changes_applied=changes_applied,
        notes_text=notes_text,
        written_text=written_text,
        patched_text=patched_text,
        commands_text=commands_text,
        observation_hash=observation_hash,
        occurred_at=occurred_at,
        stage_tokens_retrieve=stage_tokens_retrieve,
        stage_tokens_plan=stage_tokens_plan,
        stage_tokens_patch=stage_tokens_patch,
        stage_tokens_verify=stage_tokens_verify,
        story_points_raw=story_points_raw,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
