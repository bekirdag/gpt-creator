#!/usr/bin/env python3
"""Resolve a filesystem path used by the create-sds pipeline."""

import sys
from pathlib import Path
from typing import Optional


def resolve_path(raw_path: Optional[str]) -> Path:
    candidate = raw_path or "."
    return Path(candidate).expanduser().resolve()


def main() -> int:
    path_arg = sys.argv[1] if len(sys.argv) > 1 else None
    resolved = resolve_path(path_arg)
    print(resolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
