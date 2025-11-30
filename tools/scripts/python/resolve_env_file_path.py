#!/usr/bin/env python3
"""Resolve an environment file path to an absolute path."""

from __future__ import annotations

import os
import sys


def main(argv: list[str]) -> int:
    target = argv[1] if len(argv) > 1 else ""
    print(os.path.abspath(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
