#!/usr/bin/env python3
"""Print epic identifiers from the generated epics JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        return 1

    epics_path = Path(sys.argv[1])
    try:
        data = json.loads(epics_path.read_text(encoding="utf-8"))
    except Exception:
        return 1

    for epic in data.get("epics") or []:
        epic_id = (epic.get("epic_id") or "").strip()
        if epic_id:
            print(epic_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
