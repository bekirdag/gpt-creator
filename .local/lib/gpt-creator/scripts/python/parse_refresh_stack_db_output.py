#!/usr/bin/env python3
"""Parse refresh_stack_db.py JSON output into simple counts."""

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    try:
        data = json.loads(sys.argv[1])
    except Exception:
        return 1
    print(data.get("schema_rc", 1))
    print(data.get("seed_rc", 1))
    print(len(data.get("schema_applied", [])))
    print(len(data.get("seed_applied", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
