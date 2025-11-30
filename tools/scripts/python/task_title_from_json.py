#!/usr/bin/env python3
"""Extract a task title from a tasks JSON payload."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("")
        return 0

    json_path = Path(sys.argv[1])
    try:
        index = int(sys.argv[2])
    except Exception:
        print("")
        return 0

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        print("")
        return 0

    tasks = payload.get("tasks") or []
    if 0 <= index < len(tasks):
        title = (tasks[index].get("title") or "").strip()
        print(title)
    else:
        print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
