#!/usr/bin/env python3
"""Helper to archive long-form notes and emit an Action/Result pointer."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


def _infer_project_root() -> Path:
    env_value = os.environ.get("GC_PROJECT_ROOT") or os.environ.get("PROJECT_ROOT")
    if env_value:
        candidate = Path(env_value)
        try:
            return candidate.resolve()
        except Exception:
            return candidate
    return Path.cwd().resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def _build_summary(text: str, *, max_len: int = 160) -> str:
    clean = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if not clean:
        clean = text.strip()
    if not clean:
        return "(no summary available)"
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3].rstrip() + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive a long-form note under logs/notes/ and emit an Action/Result pointer.")
    parser.add_argument("title", nargs="?", help="Optional short description that will appear in the summary output.")
    parser.add_argument(
        "--stdin-label",
        dest="stdin_label",
        default="",
        help="Override label when piping text via stdin.",
    )
    args = parser.parse_args()

    input_data = sys.stdin.read()
    if not input_data.strip():
        parser.error("Expected note content via stdin; none received.")
    note_text = input_data.rstrip()

    project_root = _infer_project_root()
    notes_dir = project_root / "logs" / "notes"
    try:
        notes_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    filename = f"summary_{timestamp}.txt"
    archive_path = notes_dir / filename
    archive_path.write_text(note_text + ("\n" if not note_text.endswith("\n") else ""), encoding="utf-8")
    rel_path = _relative_path(archive_path, project_root)
    label = args.stdin_label or args.title or "long-note"
    summary = _build_summary(note_text)
    print(
        f"Action: summarize-note | Result: archived '{label}' under {rel_path}; summary: {summary}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
