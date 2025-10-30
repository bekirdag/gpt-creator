#!/usr/bin/env python3
"""Normalize --sleep-between values to a safe decimal string."""

from __future__ import annotations

import sys
from decimal import Decimal, InvalidOperation


def normalize(value: str) -> str:
    text = value.strip()
    if not text:
        text = "0"
    try:
        number = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - defensive path
        raise ValueError("invalid decimal") from exc
    if number < 0:
        raise ValueError("negative values are not allowed")
    if number == 0:
        return "0"
    normalized = number.normalize()
    rendered = format(normalized, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 1
    try:
        result = normalize(argv[1])
    except ValueError:
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
