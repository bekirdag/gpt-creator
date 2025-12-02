#!/usr/bin/env python3
"""Parse wait duration from a quota message and emit seconds."""

import re
import sys

UNITS = {
    "hour": 3600,
    "hours": 3600,
    "hr": 3600,
    "hrs": 3600,
    "h": 3600,
    "minute": 60,
    "minutes": 60,
    "min": 60,
    "mins": 60,
    "m": 60,
    "second": 1,
    "seconds": 1,
    "sec": 1,
    "secs": 1,
    "s": 1,
}


def parse_wait(message: str) -> int:
    message = (message or "").lower()
    total = 0
    for value, unit in re.findall(r"(\d+)\s*(hour|hours|hr|hrs|h|minute|minutes|min|mins|m|second|seconds|sec|secs|s)", message):
        total += int(value) * UNITS[unit]
    return total


def main(argv):
    if len(argv) != 2:
        raise SystemExit("Usage: parse_wait_seconds.py MESSAGE")
    wait = parse_wait(argv[1])
    if wait <= 0:
        wait = 3600
    print(wait)


if __name__ == "__main__":
    main(sys.argv)
