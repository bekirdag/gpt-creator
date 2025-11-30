#!/usr/bin/env python3
"""
Run a Python snippet from a file after validating it is not empty or placeholder-only.

Usage:
  1. Create a temporary snippet file (e.g. /tmp/snippet.py) via here-doc:
       cat <<'PY' > /tmp/snippet.py
       import pathlib
       print(pathlib.Path.cwd())
       PY
  2. Execute it safely:
       python3 scripts/python/run_snippet.py /tmp/snippet.py

The script refuses to execute empty files or placeholder-only snippets (`...`, `pass`, etc.)
so we avoid firing off incomplete commands during work-on-tasks runs.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path
from typing import List

PLACEHOLDER_TOKENS = {"...", "pass", "TODO", "FIXME"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute a local Python snippet file with placeholder checks.")
    parser.add_argument(
        "path",
        help="Path to the snippet file (e.g. /tmp/snippet.py).",
    )
    parser.add_argument(
        "--allow-placeholder",
        action="store_true",
        help="Skip placeholder validation (use only if you are sure the snippet is intentionally minimal).",
    )
    parser.add_argument(
        "--argv",
        nargs="*",
        default=[],
        help="Arguments to expose via sys.argv[1:] inside the snippet.",
    )
    return parser.parse_args()


def is_placeholder(content: str) -> bool:
    stripped_lines: List[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        stripped_lines.append(line)
    if not stripped_lines:
        return True
    if len(stripped_lines) == 1 and stripped_lines[0] in PLACEHOLDER_TOKENS:
        return True
    if all(line in PLACEHOLDER_TOKENS for line in stripped_lines[: min(3, len(stripped_lines))]):
        return True
    return False


def main() -> None:
    args = parse_args()
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"[run-snippet] File not found: {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="ignore")
    if not args.allow_placeholder and is_placeholder(content):
        raise SystemExit("[run-snippet] Snippet appears to be empty or placeholder-only (contains only '...' or 'pass'). Fill it before executing.")

    sys.argv = [str(path)] + args.argv
    runpy.run_path(str(path), run_name="__main__")


if __name__ == "__main__":
    main()
