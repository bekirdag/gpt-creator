#!/usr/bin/env python3
"""Mark a story slug as completed within the pipeline state file."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        return 1

    state_path = Path(sys.argv[1])
    section = sys.argv[2]
    slug = sys.argv[3]

    data = json.loads(state_path.read_text(encoding="utf-8"))
    completed = set(data.setdefault(section, {}).setdefault("completed", []))
    completed.add(slug)
    data[section]["completed"] = sorted(completed)
    state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
