#!/usr/bin/env python3
"""Verify that required documentation tables exist in the tasks database."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REQUIRED_TABLES = (
    "documentation",
    "documentation_search",
    "documentation_sections",
    "documentation_summaries",
    "documentation_excerpts",
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(1)

    db_path = Path(sys.argv[1])
    if not db_path.exists():
        raise SystemExit(1)

    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error:
        raise SystemExit(1)

    try:
        cur = conn.cursor()
        for table in REQUIRED_TABLES:
            cur.execute("SELECT name FROM sqlite_master WHERE name = ?", (table,))
            if cur.fetchone() is None:
                raise SystemExit(1)
    finally:
        conn.close()

    raise SystemExit(0)


if __name__ == "__main__":
    main()

