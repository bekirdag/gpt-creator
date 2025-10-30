#!/usr/bin/env python3
"""Return checkpoint path relative to project root when possible."""

import sys
from pathlib import Path


def main(argv):
    if len(argv) != 3:
        raise SystemExit("Usage: checkpoint_relative_path.py CHECKPOINT_PATH PROJECT_ROOT")
    file_path = Path(argv[1])
    root = Path(argv[2])
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        rel = file_path
    print(rel)


if __name__ == "__main__":
    main(sys.argv)
