#!/usr/bin/env python3
"""Validate that a tasks.db contains the required tables."""

import argparse
import sqlite3
import sys
from pathlib import Path


def check_tables(db_path: Path, required: list[str]) -> int:
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:  # pragma: no cover - thin guard
        sys.stderr.write(f"Unable to open tasks database at {db_path}: {exc}\n")
        return 2

    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    except sqlite3.Error as exc:  # pragma: no cover - thin guard
        conn.close()
        sys.stderr.write(f"Unable to read schema from {db_path}: {exc}\n")
        return 2
    finally:
        conn.close()

    names = {row[0] for row in rows}
    missing = set(required) - names
    if missing:
        missing_list = ", ".join(sorted(missing))
        sys.stderr.write(
            f"Tasks database at {db_path} is missing required tables ({missing_list}).\n"
            "Rebuild it via 'gpt-creator migrate-tasks --project <path> --force' or rerun "
            "'gpt-creator create-tasks'/'gpt-creator create-jira-tasks'.\n"
        )
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check required tables in tasks.db")
    parser.add_argument("db_path", type=Path, help="Path to tasks.db")
    parser.add_argument("tables", nargs="*", default=["epics", "stories", "tasks"])
    args = parser.parse_args()
    return check_tables(args.db_path, args.tables)


if __name__ == "__main__":
    raise SystemExit(main())
