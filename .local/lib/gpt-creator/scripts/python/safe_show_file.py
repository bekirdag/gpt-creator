#!/usr/bin/env python3
"""
Safely preview repo files without wasting tokens on missing paths.

Examples:
  python3 scripts/python/safe_show_file.py apps/api/src/admin/instructors/admin-instructor-audit.service.ts --start 1 --end 120
  python3 scripts/python/safe_show_file.py admin-instructor-audit.service.ts --suggest
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(os.environ.get("GC_PROJECT_ROOT", os.getcwd())).resolve()
DEFAULT_END = 160
MAX_SUGGESTIONS = 40


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show file slices safely; suggest real paths when your input is wrong.",
    )
    parser.add_argument(
        "target",
        help="File path (relative/absolute). If not found, the script searches by filename.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting line number (1-indexed).",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=DEFAULT_END,
        help=f"Ending line number (default: {DEFAULT_END}).",
    )
    parser.add_argument(
        "--range",
        help="Shorthand for --start/--end (format: START:END).",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=0,
        help="Show ±N lines around every match; overrides --start/--end when >0.",
    )
    parser.add_argument(
        "--match",
        help="Optional substring to highlight; expands context around hits.",
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help="Only list candidate files; skip printing contents.",
    )
    parser.add_argument(
        "--max-suggestions",
        type=int,
        default=MAX_SUGGESTIONS,
        help="Maximum number of path suggestions to list.",
    )
    return parser.parse_args()


def read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")
    return text.splitlines()


def clamp_range(start: int, end: int, total: int) -> tuple[int, int]:
    start = max(1, start)
    end = max(start, end)
    if total <= 0:
        return start, end
    start = min(start, total)
    end = min(end, total)
    return start, end


def show_slice(path: Path, start: int, end: int) -> None:
    lines = read_lines(path)
    start, end = clamp_range(start, end, len(lines))
    print(f"--- {path} (lines {start}–{end}) ---")
    for idx in range(start, end + 1):
        line = lines[idx - 1]
        print(f"{idx:>6} {line.rstrip()}")


def show_context(path: Path, needle: str, context: int) -> bool:
    lines = read_lines(path)
    matches = []
    lower_needle = needle.lower()
    for idx, line in enumerate(lines, start=1):
        if lower_needle in line.lower():
            matches.append(idx)
    if not matches:
        return False
    print(f"--- {path} (context ±{context}) ---")
    printed = set()
    for idx in matches:
        start = max(1, idx - context)
        end = min(len(lines), idx + context)
        for ln in range(start, end + 1):
            if (ln, idx) in printed:
                continue
            prefix = ">" if ln == idx else " "
            print(f"{prefix}{ln:>5} {lines[ln - 1].rstrip()}")
            printed.add((ln, idx))
        print()
    return True


def run_rg_find(name: str, max_entries: int) -> list[Path]:
    try:
        cmd = ["rg", "--files", "-g", f"*{name}*"]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=False,
        )
    except FileNotFoundError:
        return []
    if proc.returncode not in (0, 1):
        return []
    candidates: list[Path] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        candidates.append((REPO_ROOT / line.strip()).resolve())
        if len(candidates) >= max_entries:
            break
    return candidates


def suggest_paths(target: str, max_entries: int) -> list[Path]:
    # First try exact project-relative path
    rel_candidate = (REPO_ROOT / target).resolve()
    if rel_candidate.exists():
        return [rel_candidate]
    # Accept absolute paths inside repo
    abs_path = Path(target).expanduser().resolve()
    try:
        abs_path.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        if abs_path.exists():
            return [abs_path]
    # Fallback: search by filename using ripgrep
    name = Path(target).name
    return run_rg_find(name, max_entries)


def print_suggestions(paths: Sequence[Path]) -> None:
    if not paths:
        print("[safe-show] No matches found. Double-check the filename or narrow the directory.")
        return
    print("[safe-show] Did you mean:")
    for path in paths:
        try:
            rel = path.relative_to(REPO_ROOT)
        except ValueError:
            rel = path
        print(f" - {rel}")


def main() -> None:
    args = parse_args()
    if args.range:
        try:
            start_text, end_text = args.range.split(":", 1)
            args.start = int(start_text.strip() or args.start)
            args.end = int(end_text.strip() or args.end)
        except ValueError:
            print("[safe-show] Invalid --range format; expected START:END (e.g., 10:80).", file=sys.stderr)
            sys.exit(2)
    target = args.target.strip()
    candidates = suggest_paths(target, args.max_suggestions)
    if not candidates:
        print_suggestions([])
        sys.exit(1)
    path = candidates[0]
    if args.suggest:
        print_suggestions(candidates)
        return

    if args.match:
        if show_context(path, args.match, max(args.context, 2)):
            return
        print(f"[safe-show] Pattern '{args.match}' not found in {path}. Showing requested slice instead.\n")

    if args.context > 0:
        # Show context around every line within range (if no match provided)
        lines = read_lines(path)
        start, end = clamp_range(args.start, args.end, len(lines))
        print(f"--- {path} (lines {start}–{end}, context ±{args.context}) ---")
        for idx in range(start, end + 1):
            start_ctx = max(1, idx - args.context)
            end_ctx = min(len(lines), idx + args.context)
            for ln in range(start_ctx, end_ctx + 1):
                prefix = ">" if ln == idx else " "
                print(f"{prefix}{ln:>5} {lines[ln - 1].rstrip()}")
            print()
        return

    show_slice(path, args.start, args.end)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
