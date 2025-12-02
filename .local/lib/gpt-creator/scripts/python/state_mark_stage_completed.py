#!/usr/bin/env python3
"""Mark a pipeline stage as completed in the state file."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    state_path = Path(sys.argv[1])
    stage = sys.argv[2]

    data = json.loads(state_path.read_text(encoding="utf-8"))
    section = data.setdefault(stage, {})
    section["status"] = "completed"
    state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
