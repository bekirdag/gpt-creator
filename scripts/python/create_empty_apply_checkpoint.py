#!/usr/bin/env python3
"""Create an empty apply checkpoint if none exists."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("Usage: create_empty_apply_checkpoint.py ROOT STORY_SLUG TASK_ID")

    root = Path(sys.argv[1]).resolve()
    story_slug = sys.argv[2] or "story"
    task_id = sys.argv[3] or "task"

    checkpoint_dir = root / "docs/qa/evidence" / story_slug / task_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_file = checkpoint_dir / "checkpoint.md"
    if not checkpoint_file.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = (
            f"# Checkpoint — {story_slug}/{task_id}\n\n"
            "Generated automatically because the agent response contained no actionable `changes`.\n\n"
            f"- Timestamp: {timestamp}\n"
            "- Runner: gc-empty-apply-fallback\n\n"
            "## What was attempted\n"
            "- Review the raw agent output under .gpt-creator/staging/plan/work/runs for detailed context.\n"
        )
        checkpoint_file.write_text(content, encoding="utf-8")

    print(str(checkpoint_file))


if __name__ == "__main__":
    main()
