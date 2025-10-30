#!/usr/bin/env python3
"""Extract migration apply statistics as tab-separated values."""

import json
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: progress_migration_extract_apply_stats.py APPLY_JSON")

    raw = argv[1]
    try:
        payload = json.loads(raw)
    except Exception:
        print("")
        return

    stats = payload.get("stats") or {}
    updated = stats.get("tasks_updated", 0)
    preserved = stats.get("states_preserved", 0)
    locked = stats.get("states_locked", 0)
    reopened = stats.get("states_reopened", 0)
    print(f"{updated}\t{preserved}\t{locked}\t{reopened}")


if __name__ == "__main__":
    main(sys.argv)
