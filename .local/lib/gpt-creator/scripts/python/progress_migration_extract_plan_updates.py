#!/usr/bin/env python3
"""Extract task count from progress migration plan JSON."""

import json
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: progress_migration_extract_plan_updates.py PLAN_JSON")

    raw = argv[1]
    try:
        payload = json.loads(raw)
    except Exception:
        # Match previous behavior of printing empty string on failure
        print("")
        return

    total = payload.get("tasks_needing_update", 0)
    try:
        print(str(int(total)))
    except Exception:
        print("")


if __name__ == "__main__":
    main(sys.argv)
