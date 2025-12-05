#!/usr/bin/env python3
"""Lookup the help template path for a given command."""

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    cmd = sys.argv[1]
    index_path = Path(sys.argv[2])
    if not index_path.is_file():
        return 1
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return 1
    for entry in data:
        if entry.get("command") == cmd:
            tmpl = entry.get("template", "")
            if tmpl:
                print(tmpl)
                return 0
            break
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
