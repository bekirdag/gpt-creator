#!/usr/bin/env python3
"""
List JSON files in a directory (one per line), sorted by name.
Used to avoid null-byte handling issues in bash loops.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    root = Path(sys.argv[1])
    if not root.is_dir():
        return 0
    for path in sorted(root.glob("*.json")):
        try:
            sys.stdout.write(f"{path}\n")
        except Exception:
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
