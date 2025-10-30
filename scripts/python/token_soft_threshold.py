#!/usr/bin/env python3
"""Compute soft token threshold from budget and ratio."""

from __future__ import annotations

import sys


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        raise SystemExit("Usage: token_soft_threshold.py TOKEN_LIMIT RATIO")

    try:
        budget = int(argv[1])
    except Exception:
        budget = 0
    try:
        ratio = float(argv[2])
    except Exception:
        ratio = 0.9

    if budget <= 0 or ratio <= 0:
        print(0)
        return

    if ratio > 1:
        ratio = 1.0

    value = int(budget * ratio)
    if value < 0:
        value = 0
    print(value)


if __name__ == "__main__":
    main(sys.argv)
