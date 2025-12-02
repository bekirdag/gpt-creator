#!/usr/bin/env python3
"""Resolve realpath for a provided path."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_realpath(path: str) -> str:
    return os.path.realpath(path)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: resolve_realpath.py <path>", file=sys.stderr)
        return 1
    target = Path(argv[1]).expanduser()
    print(resolve_realpath(str(target)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
