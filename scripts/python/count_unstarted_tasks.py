import sqlite3
import sys
from pathlib import Path


def count_unstarted_tasks(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COUNT(*)
          FROM tasks
         WHERE LOWER(COALESCE(status, 'pending')) IN ('', 'pending')
        """
    ).fetchone()
    pending = row[0] if row else 0
    conn.close()
    return pending


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    db_path = Path(sys.argv[1])
    print(count_unstarted_tasks(db_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
