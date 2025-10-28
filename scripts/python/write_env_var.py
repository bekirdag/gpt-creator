#!/usr/bin/env python3
"""Write or update an environment variable entry in a .env-style file."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(1)

    target_path = Path(sys.argv[1])
    key = sys.argv[2]
    value = sys.argv[3]

    if target_path.exists():
        raw_lines = target_path.read_text(encoding="utf-8").splitlines()
    else:
        raw_lines = []

    lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("#") or "=" in line:
            lines.append(line)

    for idx, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[idx] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")

    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

