#!/usr/bin/env python3
"""Return file size in bytes (0 if missing)."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: file_stat_size.py PATH")

    path = Path(argv[1])
    try:
        print(path.stat().st_size)
    except FileNotFoundError:
        print(0)
    except OSError:
        print(0)


if __name__ == "__main__":
    main(sys.argv)
