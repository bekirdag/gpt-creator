#!/usr/bin/env python3
"""Mark task runs as applied when commits landed during the run.

This script is intentionally lightweight: it reads the baseline commit SHA that
the retry wrapper captured before launching work-on-tasks, inspects the most
recent run log to discover task identifiers, and then checks whether commits
between the baseline and HEAD reference any of those tasks. When it finds a
match it writes a small marker file under `.gpt-creator/logs/status-overrides/`
so downstream tooling can flip `completed-no-changes` → `complete`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / ".gpt-creator" / "logs"
BASE_SHA_FILE = LOG_DIR / "last_run.base_sha"
LAST_LOG_FILE = LOG_DIR / "last_run.log"
OVERRIDE_DIR = LOG_DIR / "status-overrides"

# Matches ADM-01-US-05-T3 or variations in the task log.
TASK_ID_PATTERN = re.compile(r"\b([A-Z]{2,}-\d+-US-\d+-T\d+)\b", re.IGNORECASE)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def capture_git_log(base_sha: str) -> list[str]:
    if not base_sha:
        return []
    try:
        output = subprocess.check_output(
            ["git", "log", f"{base_sha}..HEAD", "--pretty=format:%H%x09%s"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return []
    return [line for line in output.splitlines() if line.strip()]


def extract_task_ids(log_text: str) -> set[str]:
    ids: set[str] = set()
    for match in TASK_ID_PATTERN.finditer(log_text):
        ids.add(match.group(1).upper())
    return ids


def main() -> int:
    base_sha = read_text(BASE_SHA_FILE).strip()
    if not base_sha:
        return 0

    log_text = read_text(LAST_LOG_FILE)
    if not log_text:
        return 0

    task_ids = extract_task_ids(log_text)
    if not task_ids:
        return 0

    commit_lines = capture_git_log(base_sha)
    if not commit_lines:
        return 0

    OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)

    for line in commit_lines:
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        _, message = parts
        message_upper = message.upper()
        for task_id in task_ids:
            if task_id in message_upper:
                marker = OVERRIDE_DIR / f"{task_id}.applied"
                marker.write_text("1", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
