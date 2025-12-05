#!/usr/bin/env python3
"""Fetch an agent row from tasks.db and emit JSON payload."""

import json
import sqlite3
import sys


def main() -> int:
    if len(sys.argv) < 3:
        return 2
    db_path = sys.argv[1]
    name = (sys.argv[2] or "").strip().lower()
    if not name:
        return 2
    uri = f"file:{db_path}?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except Exception:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM agents WHERE name_normalized = ?", (name,)).fetchone()
    conn.close()
    if not row:
        return 1
    agent = dict(row)
    agent.setdefault("name", agent.get("name_normalized", ""))
    print(json.dumps({"kind": "agent", "agent": agent}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
