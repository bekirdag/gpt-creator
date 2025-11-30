#!/usr/bin/env python3
"""Reset task refinement state columns."""

import sqlite3
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: refine_tasks_reset.py TASKS_DB_PATH")

    conn = sqlite3.connect(argv[1])
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET refined = 0, refined_at = NULL")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main(sys.argv)
