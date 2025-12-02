import sqlite3
import sys
from pathlib import Path


def count_pending_tasks(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    row = cur.execute(
        "SELECT COUNT(*) FROM tasks WHERE LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) "
        "NOT IN ('complete','completed','completed-no-changes','ready-to-review','ready-to-review-no-changes','ready-for-review','ready_for_review','ready-for-qa','ready-to-qa','ready_to_qa','ready_for_qa','skipped-already-complete') "
        "AND LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) NOT LIKE 'completed-%' "
        "AND LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) NOT LIKE 'done-%' "
        "AND LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) NOT LIKE 'skipped-%' "
        "AND LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) NOT LIKE 'ready-to-review%' "
        "AND LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) NOT LIKE 'ready-for-review%' "
        "AND LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) NOT LIKE 'ready-to-qa%' "
        "AND LOWER(REPLACE(COALESCE(status, 'pending'), '_','-')) NOT LIKE 'ready-for-qa%'"
    ).fetchone()
    pending = row[0] if row else 0
    conn.close()
    return pending


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    db_path = Path(sys.argv[1])
    print(count_pending_tasks(db_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
