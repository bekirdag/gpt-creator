#!/usr/bin/env python3
"""Detect bundled story payloads shaped like {'epic_id': '...', 'user_stories': [...]}."""

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
    if isinstance(data, dict) and isinstance(data.get("user_stories"), list):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
