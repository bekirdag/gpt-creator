import sqlite3
import sys
import time
from pathlib import Path

def _is_blocked_dependency(status: str) -> bool:
    return (status or "").strip().lower().startswith("blocked-dependency(")


def update_work_state(
    db_path: Path,
    story_slug: str,
    status: str,
    completed: str,
    total: str,
    run_stamp: str,
) -> None:
    story_slug = (story_slug or "").strip()
    status_requested = (status or "pending").strip().lower()
    completed_count = int(completed or 0)
    total_count_input = int(total or 0)
    run_stamp = run_stamp or "manual"
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    row = cur.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE WHEN LOWER(COALESCE(status, '')) IN ('complete', 'completed-no-changes') THEN 1 ELSE 0 END) AS complete_count,
            SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'in-progress' THEN 1 ELSE 0 END) AS in_progress_count
          FROM tasks
         WHERE LOWER(COALESCE(story_slug, '')) = ?
        """,
        (story_slug.lower(),),
    ).fetchone()

    total_count = int(row["total_count"] or 0)
    complete_count = int(row["complete_count"] or 0)
    in_progress_count = int(row["in_progress_count"] or 0)

    if total_count > 0:
        status_final = status_requested
        if complete_count >= total_count:
            status_final = "complete"
        elif complete_count > 0 or in_progress_count > 0:
            if status_final == "complete":
                status_final = "in-progress"
            elif status_final not in {"blocked", "blocked-quota", "blocked-schema-drift", "blocked-schema-guard-error", "on-hold", "in-progress"} and not _is_blocked_dependency(status_final):
                status_final = "in-progress"
        else:
            if status_final not in {"blocked", "blocked-schema-drift", "blocked-schema-guard-error", "on-hold"} and not _is_blocked_dependency(status_final):
                status_final = "pending"
        completed_value = complete_count
        total_value = total_count
    else:
        status_final = status_requested or "pending"
        completed_value = completed_count
        total_value = total_count_input

    cur.execute(
        """
        UPDATE stories
           SET status = ?,
               completed_tasks = ?,
               total_tasks = ?,
               last_run = ?,
               updated_at = ?
         WHERE story_slug = ?
        """,
        (status_final, completed_value, total_value, run_stamp, timestamp, story_slug),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO stories (
              story_slug,
              story_key,
              status,
              completed_tasks,
              total_tasks,
              last_run,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                story_slug,
                story_slug,
                status_final,
                completed_value,
                total_value,
                run_stamp,
                timestamp,
                timestamp,
            ),
        )

    conn.commit()
    conn.close()


def main() -> int:
    if len(sys.argv) < 7:
        return 1

    db_path = Path(sys.argv[1])
    story_slug = sys.argv[2]
    status = sys.argv[3]
    completed = sys.argv[4]
    total = sys.argv[5]
    run_stamp = sys.argv[6]

    update_work_state(db_path, story_slug, status, completed, total, run_stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
