#!/usr/bin/env python3
"""Normalize duration strings (e.g., 2s, 500ms) into milliseconds."""

import math
import sys


def parse_duration(val: str) -> int:
    val = val.strip().lower()
    if val.endswith("ms"):
        return math.ceil(float(val[:-2]))
    if val.endswith("s"):
        return math.ceil(float(val[:-1]) * 1000)
    if val.endswith("m"):
        return math.ceil(float(val[:-1]) * 60_000)
    if val.endswith("h"):
        return math.ceil(float(val[:-1]) * 3_600_000)
    if val.isdigit():
        return int(val)
    raise ValueError(f"invalid duration: {val}")


def main() -> int:
    if len(sys.argv) < 2:
        return 1
    try:
        parsed = parse_duration(sys.argv[1])
    except Exception as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    print(parsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
