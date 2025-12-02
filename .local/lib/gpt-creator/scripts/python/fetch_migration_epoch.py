#!/usr/bin/env python3
"""Return the latest migration epoch recorded in tasks.db."""

import sqlite3
import sys
from pathlib import Path


def fetch_epoch(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(tasks)")
    columns = {row[1] for row in cur.fetchall()}
    if "migration_epoch" not in columns:
        conn.close()
        return 0
    row = cur.execute("SELECT COALESCE(MAX(migration_epoch), 0) FROM tasks").fetchone()
    conn.close()
    return int(row[0] or 0)


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    db_path = Path(sys.argv[1])
    epoch = fetch_epoch(db_path)
    print(epoch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
