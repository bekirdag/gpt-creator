#!/usr/bin/env python3
"""Ensure tasks table has refinement columns and report availability."""

import sqlite3
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: refine_tasks_init_db.py TASKS_DB_PATH")

    db_path = argv[1]
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(tasks)")
    cols = {row[1] for row in cur.fetchall()}
    added = False
    if "refined" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN refined INTEGER DEFAULT 0")
        added = True
    if "refined_at" not in cols:
        cur.execute("ALTER TABLE tasks ADD COLUMN refined_at TEXT")
        added = True
    if added:
        conn.commit()

    cur.execute("PRAGMA table_info(tasks)")
    cols = {row[1] for row in cur.fetchall()}
    conn.close()
    print("1" if "refined" in cols else "0")


if __name__ == "__main__":
    main(sys.argv)
