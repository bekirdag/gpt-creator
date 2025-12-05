#!/usr/bin/env python3
"""Render a template by replacing {{VAR}} with environment values."""

import os
import re
import sys
from pathlib import Path


def render(src: Path, dest: Path) -> None:
    data = src.read_text(encoding="utf-8")

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, match.group(0))

    rendered = re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", repl, data)
    dest.write_text(rendered, encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    render(src, dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
