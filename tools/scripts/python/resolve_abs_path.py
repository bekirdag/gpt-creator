#!/usr/bin/env python3
"""Resolve a filesystem path after expanding user/home references."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: resolve_abs_path.py <path>")

    path_arg = sys.argv[1] or "."
    resolved = Path(path_arg).expanduser().resolve()
    print(resolved)


if __name__ == "__main__":
    main()
