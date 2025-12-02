#!/usr/bin/env python3
"""Return success if the given state stage is marked completed."""

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
    status = (data.get(stage) or {}).get("status")
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
