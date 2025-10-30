#!/usr/bin/env python3
"""Emit SQL statements to ensure a database and user exist."""

import sys


def quote_identifier(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def quote_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main(argv: list[str]) -> None:
    if len(argv) != 5:
        raise SystemExit(
            "Usage: gc_refresh_stack_ensure_sql.py DB_NAME DB_USER DB_PASSWORD HOST"
        )

    db, user, password, host = argv[1:5]
    db = db or "app"
    user = user or "app"
    host = host or "%"

    statements = [
        f"CREATE DATABASE IF NOT EXISTS {quote_identifier(db)} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        f"CREATE USER IF NOT EXISTS {quote_string(user)}@{quote_string(host)} IDENTIFIED BY {quote_string(password)};",
        f"GRANT ALL PRIVILEGES ON {quote_identifier(db)}.* TO {quote_string(user)}@{quote_string(host)};",
        "FLUSH PRIVILEGES;",
    ]
    print("\n".join(statements))


if __name__ == "__main__":
    main(sys.argv)
