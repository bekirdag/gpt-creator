#!/usr/bin/env python3
"""Plan and apply resilient task migrations for work-on-tasks progress."""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

TERMINAL_STATUSES = {
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

AUDIT_COLUMNS: Tuple[str, ...] = (
    "uid",
    "status",
    "status_reason",
    "evidence_ptr",
    "doc_refs",
    "last_verified_commit",
    "locked_by",
    "locked_by_migration",
    "migration_epoch",
    "reopened_by_migration",
    "reopened_by_migration_at",
)

AUDIT_SELECT_COLUMNS: Tuple[str, ...] = (
    "id",
    "story_slug",
    "position",
    "task_id",
    "title",
    "uid",
    "status",
    "status_reason",
    "evidence_ptr",
    "doc_refs",
    "last_verified_commit",
    "locked_by",
    "locked_by_migration",
    "migration_epoch",
    "reopened_by_migration",
    "reopened_by_migration_at",
)


def _is_terminal(status: Optional[str]) -> bool:
    text = (status or "").strip().lower()
    return text in TERMINAL_STATUSES or text.startswith("blocked-dependency(")


def _normalise_title(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())


def _stable_uid(story_slug: str, task_id: Optional[str], title: Optional[str], position: int) -> str:
    slug = (story_slug or "").strip().lower()
    identifier = (task_id or "").strip().lower()
    title_norm = _normalise_title(title)
    if not identifier:
        identifier = f"pos:{position}"
    key = f"{slug}|{identifier}|{title_norm}"
    digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()
    return digest


def _ensure_schema(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS task_id_map(
            old_uid TEXT PRIMARY KEY,
            new_uid TEXT NOT NULL,
            epoch INTEGER NOT NULL,
            carried_status TEXT,
            carried_reason TEXT
        )
        """
    )

    def ensure_column(table: str, column: str, definition: str) -> None:
        cur.execute(f"PRAGMA table_info({table})")
        existing = {row["name"] for row in cur.fetchall()}
        if column not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    ensure_column("tasks", "uid", "TEXT")
    ensure_column("tasks", "migration_epoch", "INTEGER DEFAULT 0")
    ensure_column("tasks", "locked_by_migration", "INTEGER DEFAULT 0")
    ensure_column("tasks", "status_reason", "TEXT")
    ensure_column("tasks", "evidence_ptr", "TEXT")
    ensure_column("tasks", "doc_refs", "TEXT")
    ensure_column("tasks", "last_verified_commit", "TEXT")
    ensure_column("tasks", "locked_by", "TEXT")
    ensure_column("tasks", "reopened_by_migration_at", "TEXT")
    ensure_column("tasks", "reopened_by_migration", "INTEGER DEFAULT 0")

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_uid ON tasks(uid)
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS progress_migration_journal (
            plan_checksum TEXT PRIMARY KEY,
            epoch INTEGER NOT NULL,
            applied_at TEXT NOT NULL,
            tasks_considered INTEGER NOT NULL,
            tasks_updated INTEGER NOT NULL,
            states_preserved INTEGER NOT NULL,
            states_locked INTEGER NOT NULL,
            states_reopened INTEGER NOT NULL,
            checksum_source TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS progress_migration_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_checksum TEXT NOT NULL,
            task_id INTEGER NOT NULL,
            story_slug TEXT NOT NULL,
            task_position INTEGER NOT NULL,
            before_state TEXT NOT NULL,
            after_state TEXT NOT NULL,
            changed_fields TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_progress_migration_audit_plan
        ON progress_migration_audit(plan_checksum, task_id)
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS progress_migration_snapshots (
            plan_checksum TEXT NOT NULL,
            task_id INTEGER NOT NULL,
            before_state TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            PRIMARY KEY(plan_checksum, task_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
        """
    )


def _fetch_tasks(cur: sqlite3.Cursor) -> List[sqlite3.Row]:
    query = """
        SELECT
          id,
          story_slug,
          position,
          task_id,
          title,
          status,
          status_reason,
          evidence_ptr,
          doc_refs,
          last_verified_commit,
          uid,
          migration_epoch,
          locked_by_migration,
          locked_by
        FROM tasks
        ORDER BY story_slug, position
    """
    return list(cur.execute(query))


def _rows_checksum(rows: Sequence[sqlite3.Row]) -> str:
    hasher = hashlib.sha1()
    for row in rows:
        values = [
            row["story_slug"],
            str(row["position"]),
            row["task_id"] or "",
            row["title"] or "",
            row["status"] or "",
            row["uid"] or "",
        ]
        hasher.update("|".join(values).encode("utf-8", "replace"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _entries_checksum(entries: Sequence[Dict[str, Any]]) -> str:
    hasher = hashlib.sha1()
    for entry in sorted(
        entries,
        key=lambda item: (
            item.get("story_slug") or "",
            int(item.get("position") or 0),
            int(item.get("task_db_id") or 0),
        ),
    ):
        values = [
            str(entry.get("task_db_id") or ""),
            entry.get("old_uid") or "",
            entry.get("new_uid") or "",
            ",".join(sorted(entry.get("changes") or ())),
            str(entry.get("target_lock", "")),
        ]
        hasher.update("|".join(values).encode("utf-8", "replace"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _build_plan(rows: Sequence[sqlite3.Row], epoch: int) -> Dict[str, object]:
    per_story: Dict[str, Dict[str, int]] = {}
    entries: List[Dict[str, object]] = []
    tasks_needing_update = 0
    tasks_marked_terminal = 0

    for row in rows:
        story = row["story_slug"]
        per_story.setdefault(story, {"count": 0, "changes": 0})
        per_story[story]["count"] += 1
        uid_current = (row["uid"] or "").strip()
        new_uid = _stable_uid(story, row["task_id"], row["title"], row["position"])
        needs_uid_update = uid_current != new_uid
        carry_status = row["status"]
        carry_reason = row["status_reason"]
        terminal = _is_terminal(carry_status)
        locked_flag = int(row["locked_by_migration"] or 0)
        locked_by = (row["locked_by"] or "").strip().lower()
        target_lock = 1 if terminal else 0
        lock_flag_change = locked_flag != target_lock
        needs_locked_by_update = False
        needs_unlock_actor_reset = False
        if target_lock:
            needs_locked_by_update = locked_by != "migration"
        else:
            needs_unlock_actor_reset = locked_by == "migration"

        lock_change_required = lock_flag_change or needs_locked_by_update or needs_unlock_actor_reset
        changes: List[str] = []
        if needs_uid_update:
            changes.append("uid")
        if lock_change_required:
            changes.append("lock")
        if terminal:
            tasks_marked_terminal += 1

        if not changes:
            continue

        per_story[story]["changes"] += 1
        tasks_needing_update += 1
        entries.append(
            {
                "task_db_id": row["id"],
                "story_slug": story,
                "position": row["position"],
                "task_id": row["task_id"],
                "title": row["title"],
                "old_uid": uid_current,
                "new_uid": new_uid,
                "status": carry_status,
                "status_reason": carry_reason,
                "evidence_ptr": row["evidence_ptr"],
                "doc_refs": row["doc_refs"],
                "last_verified_commit": row["last_verified_commit"],
                "terminal": terminal,
                "target_lock": target_lock,
                "current_lock": locked_flag,
                "locked_by": row["locked_by"],
                "changes": changes,
            }
        )
    dataset_checksum = _rows_checksum(rows)
    entries_checksum = _entries_checksum(entries)
    combined_checksum = hashlib.sha1(
        f"{dataset_checksum}|{entries_checksum}".encode("utf-8", "replace")
    ).hexdigest()

    plan = {
        "epoch": epoch,
        "generated_at": _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "checksum": combined_checksum,
        "dataset_checksum": dataset_checksum,
        "entries_checksum": entries_checksum,
        "tasks_total": len(rows),
        "tasks_needing_update": tasks_needing_update,
        "tasks_marked_terminal": tasks_marked_terminal,
        "stories": per_story,
        "entries": entries,
    }
    return plan

def write_plan(plan: Dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_plan(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def append_mapping_rows(map_path: Path, epoch: int, entries: Iterable[Dict[str, object]]) -> None:
    map_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with map_path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            row = {
                "ts": timestamp,
                "epoch": epoch,
                "story_slug": entry["story_slug"],
                "position": entry["position"],
                "task_id": entry["task_id"],
                "title": entry["title"],
                "old_uid": entry["old_uid"],
                "new_uid": entry["new_uid"],
                "status": entry["status"],
                "status_reason": entry["status_reason"],
                "terminal": entry["terminal"],
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _plan_already_applied(cur: sqlite3.Cursor, checksum: str) -> bool:
    if not checksum:
        return False
    cur.execute(
        """
        SELECT 1 FROM progress_migration_journal
         WHERE plan_checksum = ?
         LIMIT 1
        """,
        (checksum,),
    )
    return cur.fetchone() is not None


def _serialise_state(row: sqlite3.Row) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for column in AUDIT_COLUMNS:
        if column in row.keys():
            payload[column] = row[column]
        else:
            payload[column] = None
    return payload


def apply_plan(db_path: Path, plan: Dict[str, object], map_path: Optional[Path]) -> Dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    cur = conn.cursor()
    _ensure_schema(cur)

    epoch = int(plan["epoch"])
    plan_checksum = str(plan.get("checksum") or "")
    entries = list(plan.get("entries") or [])

    stats = {
        "tasks_considered": 0,
        "tasks_updated": 0,
        "states_preserved": 0,
        "states_locked": 0,
        "states_reopened": 0,
    }

    applied_at = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    if not entries:
        if plan_checksum:
            checksum_source = json.dumps(
                {
                    "dataset": plan.get("dataset_checksum"),
                    "entries": plan.get("entries_checksum"),
                },
                ensure_ascii=False,
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO progress_migration_journal(
                    plan_checksum,
                    epoch,
                    applied_at,
                    tasks_considered,
                    tasks_updated,
                    states_preserved,
                    states_locked,
                    states_reopened,
                    checksum_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_checksum,
                    epoch,
                    applied_at,
                    0,
                    0,
                    0,
                    0,
                    0,
                    checksum_source,
                ),
            )
            conn.commit()
        conn.close()
        return stats

    cur.execute("PRAGMA locking_mode = EXCLUSIVE")
    cur.execute("PRAGMA busy_timeout = 8000")
    cur.execute("PRAGMA defer_foreign_keys = 1")

    if plan_checksum and _plan_already_applied(cur, plan_checksum):
        conn.close()
        return stats

    audit_rows: List[Tuple[Any, ...]] = []
    snapshot_rows: List[Tuple[Any, ...]] = []
    updated_entries: List[Dict[str, Any]] = []

    try:
        conn.execute("BEGIN IMMEDIATE")
        select_columns = ", ".join(AUDIT_SELECT_COLUMNS)
        for entry in entries:
            stats["tasks_considered"] += 1
            task_db_id = int(entry["task_db_id"])
            current = cur.execute(
                f"SELECT {select_columns} FROM tasks WHERE id = ?",
                (task_db_id,),
            ).fetchone()
            if current is None:
                continue

            before_state = _serialise_state(current)
            desired_uid = entry.get("new_uid")
            old_uid = entry.get("old_uid") or current["uid"]

            updates: Dict[str, Any] = {}
            changed_fields: List[str] = []

            if desired_uid and desired_uid != current["uid"]:
                updates["uid"] = desired_uid
                changed_fields.append("uid")

            status_now = current["status"]
            lock_target = 1 if _is_terminal(status_now) else 0
            lock_current = int(current["locked_by_migration"] or 0)
            locked_by_current_raw = current["locked_by"]
            locked_by_current = (locked_by_current_raw or "").strip().lower()
            reopened_current = int(current["reopened_by_migration"] or 0)
            reopened_at_current = current["reopened_by_migration_at"]

            if lock_target != lock_current:
                updates["locked_by_migration"] = lock_target
                changed_fields.append("locked_by_migration")

            if lock_target and locked_by_current != "migration":
                updates["locked_by"] = "migration"
                if "locked_by" not in changed_fields:
                    changed_fields.append("locked_by")
            if not lock_target and locked_by_current == "migration":
                updates["locked_by"] = None
                if "locked_by" not in changed_fields:
                    changed_fields.append("locked_by")

            if lock_target:
                if reopened_current:
                    updates["reopened_by_migration"] = 0
                    if "reopened_by_migration" not in changed_fields:
                        changed_fields.append("reopened_by_migration")
                if reopened_at_current:
                    updates["reopened_by_migration_at"] = None
                    if "reopened_by_migration_at" not in changed_fields:
                        changed_fields.append("reopened_by_migration_at")
            else:
                if not reopened_current:
                    updates["reopened_by_migration"] = 1
                    if "reopened_by_migration" not in changed_fields:
                        changed_fields.append("reopened_by_migration")
                    updates["reopened_by_migration_at"] = applied_at
                    if "reopened_by_migration_at" not in changed_fields:
                        changed_fields.append("reopened_by_migration_at")

            if not updates:
                continue

            updates["migration_epoch"] = epoch

            set_clauses: List[str] = []
            params: List[Any] = []
            for column, value in updates.items():
                if value is None:
                    set_clauses.append(f"{column} = NULL")
                else:
                    set_clauses.append(f"{column} = ?")
                    params.append(value)
            params.append(task_db_id)

            cur.execute(
                f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?",
                params,
            )
            if cur.rowcount == 0:
                continue

            stats["tasks_updated"] += 1
            lock_after = updates.get("locked_by_migration", lock_current)
            if lock_after == lock_current:
                stats["states_preserved"] += 1
            elif lock_after == 1:
                stats["states_locked"] += 1
            else:
                stats["states_reopened"] += 1

            after_state = dict(before_state)
            for column, value in updates.items():
                after_state[column] = value

            before_json = json.dumps(before_state, ensure_ascii=False)
            after_json = json.dumps(after_state, ensure_ascii=False)
            changed_json = json.dumps(sorted(set(changed_fields)), ensure_ascii=False)

            audit_rows.append(
                (
                    plan_checksum,
                    task_db_id,
                    current["story_slug"],
                    current["position"],
                    before_json,
                    after_json,
                    changed_json,
                    applied_at,
                )
            )
            snapshot_rows.append(
                (
                    plan_checksum,
                    task_db_id,
                    before_json,
                    applied_at,
                )
            )

            if desired_uid:
                cur.execute(
                    """
                    INSERT INTO task_id_map(old_uid, new_uid, epoch, carried_status, carried_reason)
                    VALUES(?, ?, ?, ?, ?)
                    ON CONFLICT(old_uid) DO UPDATE SET
                      new_uid = excluded.new_uid,
                      epoch = excluded.epoch,
                      carried_status = excluded.carried_status,
                      carried_reason = excluded.carried_reason
                    """,
                    (
                        old_uid or desired_uid,
                        desired_uid,
                        epoch,
                        entry.get("status"),
                        entry.get("status_reason"),
                    ),
                )

            updated_entries.append(entry)

        if snapshot_rows:
            cur.executemany(
                """
                INSERT OR IGNORE INTO progress_migration_snapshots(
                    plan_checksum,
                    task_id,
                    before_state,
                    captured_at
                ) VALUES (?, ?, ?, ?)
                """,
                snapshot_rows,
            )

        if audit_rows:
            cur.executemany(
                """
                INSERT INTO progress_migration_audit(
                    plan_checksum,
                    task_id,
                    story_slug,
                    task_position,
                    before_state,
                    after_state,
                    changed_fields,
                    applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                audit_rows,
            )

        checksum_source = json.dumps(
            {
                "dataset": plan.get("dataset_checksum"),
                "entries": plan.get("entries_checksum"),
            },
            ensure_ascii=False,
        )

        if plan_checksum:
            cur.execute(
                """
                INSERT OR REPLACE INTO progress_migration_journal(
                    plan_checksum,
                    epoch,
                    applied_at,
                    tasks_considered,
                    tasks_updated,
                    states_preserved,
                    states_locked,
                    states_reopened,
                    checksum_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_checksum,
                    epoch,
                    applied_at,
                    stats["tasks_considered"],
                    stats["tasks_updated"],
                    stats["states_preserved"],
                    stats["states_locked"],
                    stats["states_reopened"],
                    checksum_source,
                ),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if map_path is not None and updated_entries:
        append_mapping_rows(map_path, epoch, updated_entries)

    return stats


def plan_only(db_path: Path, plan_path: Path) -> Dict[str, object]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    _ensure_schema(cur)
    rows = _fetch_tasks(cur)
    conn.close()
    epoch = int(time.time())
    plan = _build_plan(rows, epoch)
    write_plan(plan, plan_path)
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan/apply resilient task migrations.")
    sub = parser.add_subparsers(dest="mode", required=True)

    plan_parser = sub.add_parser("plan", help="Generate migration plan without applying changes.")
    plan_parser.add_argument("--db", required=True, type=Path, help="Path to tasks.db")
    plan_parser.add_argument("--output", required=True, type=Path, help="Plan JSON destination")

    apply_parser = sub.add_parser("apply", help="Apply a previously generated migration plan.")
    apply_parser.add_argument("--db", required=True, type=Path, help="Path to tasks.db")
    apply_parser.add_argument("--plan", required=True, type=Path, help="Plan JSON path")
    apply_parser.add_argument("--map-log", type=Path, help="Append mapping rows to NDJSON file")

    args = parser.parse_args(argv)

    if args.mode == "plan":
        plan = plan_only(args.db, args.output)
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "epoch": plan["epoch"],
                    "tasks_total": plan["tasks_total"],
                    "tasks_needing_update": plan["tasks_needing_update"],
                }
            )
        )
        return 0

    if args.mode == "apply":
        plan = load_plan(args.plan)
        stats = apply_plan(args.db, plan, args.map_log)
        print(
            json.dumps(
                {
                    "mode": "apply",
                    "epoch": plan.get("epoch"),
                    "stats": stats,
                }
            )
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
