#!/usr/bin/env python3
import sqlite3
import sys


def main(argv):
    if len(argv) < 4:
        return 0

    db_path, story_slug, position = argv[1], argv[2], argv[3]

    try:
        position_int = int(position)
    except (TypeError, ValueError):
        return 0

    row = None
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            (
                "SELECT COALESCE(last_attempt_signature, ''), "
                "COALESCE(last_changes_count, 0), "
                "COALESCE(last_outcome_reason, '') "
                "FROM tasks WHERE story_slug = ? AND position = ?"
            ),
            (story_slug, position_int),
        )
        row = cur.fetchone()
    except sqlite3.DatabaseError:
        row = None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if row:
        print("\t".join(str(item) for item in row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
