#!/usr/bin/env python3
"""Check whether package.json declares a given script."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def has_script(script_name: str, package_path: Path) -> bool:
    try:
        with package_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return False

    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return False
    value = scripts.get(script_name)
    if isinstance(value, str):
        return value.strip() != ""
    return bool(value)


def main() -> int:
    script_name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not script_name:
        return 1
    package_path = Path("package.json")
    if not package_path.is_file():
        return 1
    return 0 if has_script(script_name, package_path) else 1


if __name__ == "__main__":
    raise SystemExit(main())
