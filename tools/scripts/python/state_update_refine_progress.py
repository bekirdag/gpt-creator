#!/usr/bin/env python3
"""Update refine progress tracking for a story slug."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 5:
        return 1

    state_path = Path(sys.argv[1])
    slug = sys.argv[2]
    next_task = int(sys.argv[3])
    total = int(sys.argv[4])

    data = json.loads(state_path.read_text(encoding="utf-8"))
    stories = data.setdefault("refine", {}).setdefault("stories", {})
    record = stories.setdefault(slug, {})

    if next_task >= total:
        record["status"] = "done"
        record.pop("next_task", None)
    else:
        record["status"] = "in-progress"
        record["next_task"] = next_task

    stories[slug] = record
    state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
