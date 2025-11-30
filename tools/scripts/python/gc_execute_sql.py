#!/usr/bin/env python3
"""Extract fallback database credentials from SQL initialization script."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract_credentials(sql_text: str) -> tuple[str, str] | tuple[None, None]:
    """Return (user, password) if both are present, otherwise (None, None)."""

    user_match = re.search(r"CREATE\s+USER\s+IF\s+NOT\s+EXISTS\s+'([^']+)'", sql_text, re.IGNORECASE)
    password_match = re.search(r"IDENTIFIED\s+BY\s+'([^']+)'", sql_text, re.IGNORECASE)
    if user_match and password_match:
        return user_match.group(1), password_match.group(1)
    return None, None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 1

    sql_path = Path(argv[1])
    try:
        sql_text = sql_path.read_text()
    except FileNotFoundError:
        return 0
    except OSError:
        return 0

    user, password = extract_credentials(sql_text)
    if user and password:
        print(user)
        print(password)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
