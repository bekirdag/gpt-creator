#!/usr/bin/env python3
"""Return success if tasks JSON has at least one task."""

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    path = Path(sys.argv[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 1
    tasks = data.get("tasks")
    if isinstance(tasks, list) and len(tasks) > 0:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
