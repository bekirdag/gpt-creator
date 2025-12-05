#!/usr/bin/env python3
"""Pick a Detox configuration name for a given platform."""

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    root = Path(sys.argv[1])
    platform = sys.argv[2].lower()
    pkg = root / "package.json"
    if not pkg.exists():
        return 1
    try:
        data = json.loads(pkg.read_text())
    except Exception:
        return 1
    configs = data.get("detox", {}).get("configurations", {}) or {}
    if not configs:
        return 1
    for name in configs:
        if platform in name.lower():
            print(name)
            return 0
    print(next(iter(configs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
