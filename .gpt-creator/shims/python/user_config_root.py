#!/usr/bin/env python3
"""Determine the per-user configuration root directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_config_dir() -> str:
    if sys.platform.startswith("win"):
        for key in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(key)
            if base:
                return base
    try:
        home = Path.home()
    except Exception:
        home = None
    else:
        if sys.platform == "darwin":
            return str(home / "Library" / "Application Support")

    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return base
    if home is not None:
        return str(home / ".config")
    return "."


def main() -> None:
    print(user_config_dir())


if __name__ == "__main__":
    main()

