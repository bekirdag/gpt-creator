#!/usr/bin/env python3
"""Check whether a story slug is marked completed and keep state consistent."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 5:
        return 1

    state_path = Path(sys.argv[1])
    section = sys.argv[2]
    slug = sys.argv[3]
    target_path = Path(sys.argv[4])

    data = json.loads(state_path.read_text(encoding="utf-8"))
    section_obj = data.get(section) or {}
    completed_list = section_obj.get("completed") or []
    completed = set(completed_list)

    if slug in completed and not target_path.exists():
        completed.discard(slug)
        sect = data.setdefault(section, {})
        sect["completed"] = sorted(completed)
        sect["status"] = "pending"
        state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return 1

    if slug in completed:
        return 0

    sect = data.setdefault(section, {})
    if sect.get("status") == "completed":
        sect["status"] = "pending"
        state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
