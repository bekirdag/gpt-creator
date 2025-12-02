#!/usr/bin/env python3
"""Print a numbered slice of a file without using disallowed shell pipelines."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show a range of lines from a file.")
    parser.add_argument("path", help="Path to the file")
    parser.add_argument("--start", type=int, default=1, help="1-based start line (default: 1)")
    parser.add_argument("--end", type=int, default=None, help="1-based end line (inclusive)")
    parser.add_argument("--head", type=int, default=None, help="Show the first N lines")
    parser.add_argument("--tail", type=int, default=None, help="Show the last N lines")
    parser.add_argument("--no-numbers", dest="numbers", action="store_false", help="Disable line numbers")
    return parser.parse_args()


def select_lines(lines: list[str], start: int, end: int | None, head: int | None, tail: int | None) -> tuple[list[str], int]:
    total = len(lines)
    if head is not None:
        end = min(total, head)
        return lines[:end], 1
    if tail is not None:
        tail = max(0, tail)
        snippet = lines[-tail:] if tail else []
        start_line = total - len(snippet) + 1 if snippet else total
        return snippet, start_line
    if start < 1:
        start = 1
    if end is None or end < start:
        end = start
    if end > total:
        end = total
    return lines[start - 1 : end], start


def main() -> int:
    args = parse_args()
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}")
        return 1
    text_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    snippet, start_line = select_lines(text_lines, args.start, args.end, args.head, args.tail)
    if not snippet:
        print("(no lines to display)")
        return 0
    for offset, line in enumerate(snippet):
        if args.numbers:
            print(f"{start_line + offset:>6}  {line}")
        else:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
