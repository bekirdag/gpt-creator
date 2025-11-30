#!/usr/bin/env python3
"""Merge budget tool actions from an environment JSON payload and prefixed variables."""

import json
import os
import sys


def main(argv) -> None:
    base_raw = argv[1] if len(argv) > 1 else ""
    try:
        base = json.loads(base_raw) if base_raw else {}
    except json.JSONDecodeError:
        base = {}
    if not isinstance(base, dict):
        base = {}

    prefix = "GC_BUDGET_TOOL_ACTION_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        tool = key[len(prefix):].lower().replace("_", "-")
        if value:
            base[tool] = value

    print(json.dumps(base, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main(sys.argv)
