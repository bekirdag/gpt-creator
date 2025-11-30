#!/usr/bin/env python3
"""Perform auto-commit logic for work-on-tasks."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Tuple

SKIP_PREFIXES = (
    "tmp/",
    ".gpt-creator/staging/plan/work/runs/",
    ".gpt-creator/work/",
    ".gpt-creator/logs/",
    ".gpt-creator/cache/",
)


def emit(level: str, message: str) -> None:
    print(f"MESSAGE\t{level}\t{message}")


def emit_result(status: str, commit_hash: str) -> None:
    print(f"RESULT\t{status}\t{commit_hash}")


def sanitize_message(message: str) -> str:
    clean = " ".join(message.replace("\r", " ").replace("\n", " ").split())
    if len(clean) > 72:
        return clean[:69] + "..."
    return clean


def normalize_path(raw: str, project_root: Path) -> str | None:
    path = raw.split(" (", 1)[0].strip()
    if not path:
        return None
    try:
        path_obj = Path(path)
        if path_obj.is_absolute():
            try:
                path_obj = path_obj.relative_to(project_root)
            except ValueError:
                pass
        else:
            if path.startswith(str(project_root) + "/"):
                path_obj = Path(path[len(str(project_root)) + 1 :])
    except Exception:
        path_obj = Path(path)

    norm = str(path_obj).replace("\\", "/")
    if not norm:
        return None
    if norm.endswith(".rej"):
        return None
    for prefix in SKIP_PREFIXES:
        if norm.startswith(prefix):
            return None
    return norm


def ensure_unique_paths(paths: Iterable[str]) -> Tuple[str, ...]:
    seen = set()
    unique = []
    for path in paths:
        if path and path not in seen:
            unique.append(path)
            seen.add(path)
    return tuple(unique)


def run_git(args: list[str], project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(project_root),
        check=False,
        text=True,
        capture_output=True,
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        emit("warn", "Auto-commit helper requires at least a commit message.")
        emit_result("skipped", "")
        return 0

    commit_message = argv[1]
    raw_paths = argv[2:]

    project_root_env = os.environ.get("PROJECT_ROOT")
    if not project_root_env:
        emit("info", "Auto-commit skipped: project root unavailable.")
        emit_result("skipped", "")
        return 0

    project_root = Path(project_root_env)
    if not project_root.exists():
        emit("warn", f"Auto-commit skipped: project root missing ({project_root}).")
        emit_result("skipped", "")
        return 0

    if shutil.which("git") is None:
        emit("info", "Auto-commit skipped: git command not found.")
        emit_result("skipped", "")
        return 0

    inside_proc = run_git(["rev-parse", "--is-inside-work-tree"], project_root)
    if inside_proc.returncode != 0:
        emit("info", "Auto-commit skipped: not a git repository.")
        emit_result("skipped", "")
        return 0

    normalized_paths = [normalize_path(raw, project_root) for raw in raw_paths]
    stage_paths = ensure_unique_paths(path for path in normalized_paths if path)

    if not stage_paths:
        emit("info", "Auto-commit skipped: no paths to stage.")
        emit_result("clean", "")
        return 0

    sanitized_message = sanitize_message(commit_message)

    add_proc = run_git(["add", "--", *stage_paths], project_root)
    if add_proc.returncode != 0:
        emit("warn", f"Auto-commit staging failed: {add_proc.stderr.strip() or add_proc.stdout.strip()}")
        emit_result("failed", "")
        return 0

    diff_proc = run_git(["diff", "--cached", "--quiet", "--exit-code"], project_root)
    if diff_proc.returncode == 0:
        emit("info", "Auto-commit skipped: staged state clean.")
        emit_result("clean", "")
        return 0

    commit_proc = run_git(["commit", "-m", sanitized_message], project_root)
    if commit_proc.returncode != 0:
        emit("warn", f"Auto-commit failed: {commit_proc.stderr.strip() or commit_proc.stdout.strip()}")
        emit_result("failed", "")
        return 0

    hash_proc = run_git(["rev-parse", "HEAD"], project_root)
    commit_hash = hash_proc.stdout.strip() if hash_proc.returncode == 0 else ""
    if commit_hash:
        emit("info", f"Auto-commit {commit_hash[:7]}: {sanitized_message}")
    else:
        emit("info", f"Auto-commit created: {sanitized_message}")
    emit_result("committed", commit_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
