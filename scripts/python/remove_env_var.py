#!/usr/bin/env python3
"""Remove an environment variable entry from a .env-style file."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(1)

    target_path = Path(sys.argv[1])
    key = sys.argv[2]

    if not target_path.exists():
        raise SystemExit(0)

    lines = target_path.read_text(encoding="utf-8").splitlines()
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            filtered.append(line)
            continue
        if line.startswith(f"{key}=") or line.startswith(f"export {key}="):
            continue
        filtered.append(line)

    target_path.write_text("\n".join(filtered) + ("\n" if filtered else ""), encoding="utf-8")


if __name__ == "__main__":
    main()

