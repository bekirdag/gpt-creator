#!/usr/bin/env python3
"""Runtime dispatcher for work-on-tasks (split into apply/prompt modules)."""

from __future__ import annotations

import sys
from pathlib import Path

FILE_DIR = Path(__file__).resolve().parent
if str(FILE_DIR) not in sys.path:
    sys.path.insert(0, str(FILE_DIR))

from work_on_tasks_shared import *  # noqa: F401,F403
from work_on_tasks_shared import _silence_prompt_logs, _autoformat_note_entry, _has_action_token  # re-exported for tests/backwards compat


def main() -> None:
    _silence_prompt_logs()
    if len(sys.argv) < 2:
        print("Usage: work_on_tasks_runtime.py <apply|prompt> …", file=sys.stderr)
        sys.exit(1)
    mode = sys.argv[1]
    args = sys.argv[2:]
    if mode == "apply":
        from work_on_tasks_apply import run_apply
        run_apply(args)
    elif mode == "prompt":
        from work_on_tasks_prompt import run_prompt
        run_prompt(args)
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
