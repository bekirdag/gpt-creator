#!/usr/bin/env python3
"""Emit SHA-1 hash for git diff payload text."""

import hashlib
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: diff_payload_hash.py PAYLOAD")

    data = argv[1].encode("utf-8", "replace")
    print(hashlib.sha1(data).hexdigest())


if __name__ == "__main__":
    main(sys.argv)
