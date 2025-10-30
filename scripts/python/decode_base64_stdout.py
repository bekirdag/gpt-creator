#!/usr/bin/env python3
"""Decode base64 data and print UTF-8 text."""

import base64
import sys


def main(argv):
    if len(argv) != 2:
        raise SystemExit("Usage: decode_base64_stdout.py BASE64_TEXT")
    data = base64.b64decode(argv[1])
    print(data.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    main(sys.argv)
