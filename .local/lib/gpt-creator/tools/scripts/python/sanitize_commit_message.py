#!/usr/bin/env python3
"""Sanitize an auto-commit message for git."""

import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: sanitize_commit_message.py MESSAGE")

    msg = argv[1]
    msg = " ".join(msg.replace("\r", " ").replace("\n", " ").split())
    print((msg[:69] + "...") if len(msg) > 72 else msg)


if __name__ == "__main__":
    main(sys.argv)
