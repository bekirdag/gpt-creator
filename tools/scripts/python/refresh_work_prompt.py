#!/usr/bin/env python3
"""No-op prompt refresh helper for work-on-tasks.

The historical helper could rewrite prompts with injected guards; to keep runs
resilient when the helper is missing, we provide a lightweight shim that simply
copies the base prompt to the target path (or leaves the existing prompt
untouched if the base is unavailable). This prevents missing-helper crashes
during work-on-tasks.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main(args: list[str]) -> int:
    if len(args) < 2:
        return 0
    prompt_base = Path(args[0])
    prompt_path = Path(args[1])
    if prompt_base.is_file():
        try:
            shutil.copy(prompt_base, prompt_path)
        except Exception:
            # Ignore copy failures; downstream steps will use whatever prompt exists.
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
