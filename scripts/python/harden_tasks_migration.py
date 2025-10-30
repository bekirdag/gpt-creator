import sqlite3
import sys
from pathlib import Path


def ensure_column(cur: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    if not any(row["name"] == column for row in cur.fetchall()):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def harden_tasks(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ensure_column(cur, "tasks", "locked_by", "TEXT")
    ensure_column(cur, "tasks", "reopened_by_migration_at", "TEXT")
    ensure_column(cur, "tasks", "reopened_by_migration", "INTEGER DEFAULT 0")

    cur.execute(
        """
        UPDATE tasks
           SET reopened_by_migration = 0
         WHERE reopened_by_migration IS NULL
        """
    )
    cur.execute(
        """
        UPDATE tasks
           SET locked_by = 'migration'
         WHERE LOWER(COALESCE(status, '')) IN ('complete', 'completed-no-changes')
           AND (locked_by IS NULL OR TRIM(locked_by) = '')
        """
    )

    conn.commit()
    conn.close()


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    db_path = Path(sys.argv[1])
    if not db_path.exists():
        return 0
    harden_tasks(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
