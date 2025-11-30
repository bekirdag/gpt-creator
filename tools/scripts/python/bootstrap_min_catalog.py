#!/usr/bin/env python3
"""Bootstrap a minimal documentation catalog SQLite database."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, slug TEXT, title TEXT, path TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS sections(
  id TEXT PRIMARY KEY, doc_id TEXT, title TEXT, start_line INTEGER, end_line INTEGER
);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def ensure_parent(path: Path) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)


def bootstrap_catalog(db_path: Path) -> None:
    ensure_parent(db_path)
    connection = sqlite3.connect(str(db_path))
    try:
        cursor = connection.cursor()
        cursor.executescript(SCHEMA_SQL)
        cursor.execute(
            "INSERT OR REPLACE INTO meta(k, v) VALUES('created_at', ?)",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ"),),
        )
        connection.commit()
    finally:
        connection.close()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: bootstrap_min_catalog.py <catalog-db-path>", file=sys.stderr)
        return 1
    db_path = Path(argv[1]).expanduser()
    bootstrap_catalog(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
