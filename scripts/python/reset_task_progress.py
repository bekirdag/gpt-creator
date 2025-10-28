import sqlite3
import sys
import time
from pathlib import Path


def reset_task_progress(db_path: Path) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE stories
           SET status = 'pending',
               completed_tasks = 0,
               last_run = NULL,
               updated_at = ?
        """,
        (timestamp,),
    )
    cur.execute(
        """
        UPDATE tasks
           SET status = 'pending',
               started_at = NULL,
               completed_at = NULL,
               last_run = NULL,
               last_log_path = NULL,
               last_prompt_path = NULL,
               last_output_path = NULL,
               last_attempts = NULL,
               last_tokens_total = NULL,
               last_duration_seconds = NULL,
               last_apply_status = NULL,
               last_changes_applied = NULL,
               last_notes_json = NULL,
               last_written_json = NULL,
               last_patched_json = NULL,
               last_commands_json = NULL,
               last_progress_at = NULL,
               last_progress_run = NULL,
               updated_at = ?
        """,
        (timestamp,),
    )

    try:
        cur.execute("DELETE FROM task_progress")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    db_path = Path(sys.argv[1])
    reset_task_progress(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
