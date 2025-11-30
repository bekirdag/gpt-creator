#!/usr/bin/env python3
"""Generate a stable SHA-256 hash for observation seeds."""

import hashlib
import sys


def main(argv: list[str]) -> None:
    seed = argv[1] if len(argv) > 1 else ""
    if not seed:
        raise SystemExit(1)
    print(hashlib.sha256(seed.encode()).hexdigest())


if __name__ == "__main__":
    main(sys.argv)
