#!/usr/bin/env python3
"""Report and update refine progress for a given story slug."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        return 1

    state_path = Path(sys.argv[1])
    slug = sys.argv[2]
    try:
        total = int(sys.argv[3])
    except Exception:
        print(0)
        return 0

    data = json.loads(state_path.read_text(encoding="utf-8"))
    stories = data.setdefault("refine", {}).setdefault("stories", {})
    record = stories.get(slug)
    if not record:
        print(0)
        return 0
    if record.get("status") == "done":
        print("done")
        return 0
    next_task = int(record.get("next_task", 0))
    if next_task >= total:
        record["status"] = "done"
        record.pop("next_task", None)
        stories[slug] = record
        state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print("done")
    else:
        print(next_task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
