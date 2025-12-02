import sqlite3
import sys
from pathlib import Path


def tasks_db_has_rows(db_path: Path) -> int:
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.DatabaseError:
        return 1

    stories = 0
    tasks = 0
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM stories")
        row = cur.fetchone()
        stories = int(row[0]) if row and row[0] is not None else 0
        cur.execute("SELECT COUNT(*) FROM tasks")
        row = cur.fetchone()
        tasks = int(row[0]) if row and row[0] is not None else 0
    except sqlite3.DatabaseError:
        conn.close()
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return 0 if stories > 0 and tasks > 0 else 1


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    db_path = Path(sys.argv[1])
    return tasks_db_has_rows(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
