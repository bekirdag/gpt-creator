#!/usr/bin/env python3
"""Resolve an absolute path, mirroring the shell helper behaviour."""

from __future__ import annotations

import os
import sys


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    print(os.path.abspath(target))


if __name__ == "__main__":
    main()
