#!/usr/bin/env python3
"""Mark the work-on-tasks state file as aborted due to an interrupt signal."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

NOTE = "aborted due to SIGINT/SIGTERM; safe to retry"


def update_state(path: Path) -> None:
    if not path.exists():
        state: dict[str, object] = {}
    else:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except Exception:
            state = {}

    last_run = state.setdefault("last_run", {})
    if isinstance(last_run, dict):
        last_run["apply_status"] = "aborted"
    else:
        state["last_run"] = {"apply_status": "aborted"}

    state["interrupted_by_signal"] = True

    notes = state.setdefault("notes", [])
    if isinstance(notes, list):
        notes.append(NOTE)
    else:
        state["notes"] = [NOTE]

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(1)
    target = Path(sys.argv[1])
    update_state(target)


if __name__ == "__main__":
    main()
