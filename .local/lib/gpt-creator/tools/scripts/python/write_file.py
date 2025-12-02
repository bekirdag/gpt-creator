#!/usr/bin/env python3
"""Simple file writer helper to avoid heredocs in automated flows."""

import argparse
import base64
from pathlib import Path
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write content to a file safely.")
    parser.add_argument(
        "--path",
        required=True,
        help="Destination path for the file to write.",
    )
    parser.add_argument(
        "--mode",
        default="0644",
        help="File mode (octal string, default 0644).",
    )
    parser.add_argument(
        "--base64",
        action="store_true",
        help="Treat the provided content/stdin as base64-encoded.",
    )
    parser.add_argument(
        "content",
        nargs="?",
        help="Optional inline content. If omitted, reads from stdin.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = Path(args.path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if args.content is None:
        data = sys.stdin.buffer.read()
    else:
        data = args.content.encode("utf-8")

    if args.base64:
        data = base64.b64decode(data)

    destination.write_bytes(data)

    try:
        destination.chmod(int(args.mode, 8))
    except ValueError:
        # Ignore invalid mode values; file is already written.
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
