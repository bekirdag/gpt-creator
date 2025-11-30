#!/usr/bin/env python3
"""Decode base64 input and print the UTF-8 text, ignoring errors."""

from __future__ import annotations

import base64
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(0)
    data = sys.argv[1]
    try:
        decoded = base64.b64decode(data).decode("utf-8")
    except Exception:
        return
    sys.stdout.write(decoded)


if __name__ == "__main__":
    main()

