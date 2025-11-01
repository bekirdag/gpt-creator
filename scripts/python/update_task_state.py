import sqlite3
import sys
import time
from pathlib import Path

LOCKABLE_STATUSES = {
    "complete",
    "completed",
    "completed-no-changes",
    "blocked-budget",
    "blocked-quota",
    "blocked-merge-conflict",
    "blocked-schema-drift",
    "blocked-schema-guard-error",
    "blocked-push",
    "skipped-already-complete",
}


def _is_blocked_dependency(status: str) -> bool:
    return (status or "").strip().lower().startswith("blocked-dependency(")


def update_task_state(
    db_path: Path,
    story_slug: str,
    position: str,
    status: str,
    run_stamp: str,
) -> None:
    position_int = int(position)
    run_stamp = run_stamp or "manual"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, status, started_at, completed_at, locked_by_migration,
               reopened_by_migration, reopened_by_migration_at
          FROM tasks
         WHERE story_slug = ? AND position = ?
        """,
        (story_slug, position_int),
    ).fetchone()

    if row is not None:
        current_status = (row["status"] or "").strip().lower()
        locked_by_migration = int(row["locked_by_migration"] or 0)
        reopened_by_migration = int(row["reopened_by_migration"] or 0)
        status_lower = (status or "").strip().lower()

        if locked_by_migration and status_lower not in LOCKABLE_STATUSES and not _is_blocked_dependency(status_lower):
            allow_reopen = False
            if status_lower in {"pending", "in-progress"}:
                allow_reopen = True
            elif status_lower == current_status:
                allow_reopen = True
            elif status_lower == "blocked-migration-transition":
                allow_reopen = True
            if not allow_reopen:
                conn.close()
                return

        fields = [
            ("status", status),
            ("last_run", run_stamp),
            ("updated_at", timestamp),
        ]

        started_at = row["started_at"]
        completed_at = row["completed_at"]

        if status == "in-progress" and not started_at:
            fields.append(("started_at", timestamp))
        elif status == "complete":
            if not started_at:
                fields.append(("started_at", timestamp))
            fields.append(("completed_at", timestamp))
        elif status == "pending":
            fields.append(("started_at", None))
            fields.append(("completed_at", None))
        elif status in {"blocked", "blocked-quota", "blocked-schema-drift", "blocked-schema-guard-error"} or _is_blocked_dependency(status):
            if not started_at:
                fields.append(("started_at", timestamp))

        if locked_by_migration and status_lower not in LOCKABLE_STATUSES and not _is_blocked_dependency(status_lower):
            fields.append(("locked_by_migration", 0))
            fields.append(("reopened_by_migration", 1))
            if not reopened_by_migration:
                fields.append(("reopened_by_migration_at", timestamp))
        elif status_lower in LOCKABLE_STATUSES or _is_blocked_dependency(status_lower):
            fields.append(("locked_by_migration", 1))

        set_clause = ", ".join(f"{col} = ?" for col, _ in fields)
        params = [value for _, value in fields] + [story_slug, position_int]
        cur.execute(f"UPDATE tasks SET {set_clause} WHERE story_slug = ? AND position = ?", params)

    conn.commit()
    conn.close()


def main() -> int:
    if len(sys.argv) < 6:
        return 1

    db_path = Path(sys.argv[1])
    story_slug = sys.argv[2]
    position = sys.argv[3]
    status = sys.argv[4]
    run_stamp = sys.argv[5]

    update_task_state(db_path, story_slug, position, status, run_stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
