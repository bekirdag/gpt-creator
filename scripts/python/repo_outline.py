#!/usr/bin/env python3
"""
Quick repository outline helper.

Instead of running a dozen separate `ls` or `sed` commands just to understand
the project layout, call this script once to print a trimmed directory tree (and
optional file samples). The output is intentionally small so it can be pasted
into a task log without blowing the token budget.
"""

from __future__ import annotations

import argparse
import itertools
import os
from pathlib import Path
from typing import Iterable, Iterator, Sequence

DEFAULT_IGNORE = {
    ".git",
    ".gpt-creator",
    ".idea",
    ".turbo",
    "node_modules",
    "dist",
    "tmp",
    "tmp-retention-build",
    "__pycache__",
    ".next",
    ".pnpm",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print a concise tree of repo directories/files.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Root directory to inspect (defaults to current working directory).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="How many directory levels to show for the main outline.",
    )
    parser.add_argument(
        "--files-per-dir",
        type=int,
        default=5,
        help="Number of files to preview per directory (0 to disable).",
    )
    parser.add_argument(
        "--focus",
        action="append",
        default=[],
        help="Relative paths to print in greater detail (can repeat).",
    )
    parser.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Additional directory or file names to skip.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Show entries that start with '.' (hidden files).",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=20,
        help="Maximum entries per directory (directories + files).",
    )
    return parser.parse_args()


def should_skip(path: Path, include_hidden: bool, ignore: set[str]) -> bool:
    name = path.name
    if not include_hidden and name.startswith("."):
        return True
    if name in ignore:
        return True
    return False


def list_directory(path: Path) -> Sequence[Path]:
    try:
        return sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except FileNotFoundError:
        return []


def format_entry(prefix: str, name: str) -> str:
    return f"{prefix}{name}"


def walk_tree(
    root: Path,
    *,
    depth: int,
    max_depth: int,
    files_per_dir: int,
    include_hidden: bool,
    ignore: set[str],
    max_items: int,
) -> Iterator[str]:
    if depth > max_depth:
        return
    rel_prefix = "  " * depth
    entries = list_directory(root)
    visible = [
        entry
        for entry in entries
        if not should_skip(entry, include_hidden=include_hidden, ignore=ignore)
    ]
    if depth == 0:
        yield format_entry("", root.resolve().name + "/")
    for entry in itertools.islice(visible, max_items):
        indicator = "/" if entry.is_dir() else ""
        yield format_entry(rel_prefix, f"- {entry.name}{indicator}")
        if entry.is_dir():
            yield from walk_tree(
                entry,
                depth=depth + 1,
                max_depth=max_depth,
                files_per_dir=files_per_dir,
                include_hidden=include_hidden,
                ignore=ignore,
                max_items=max_items,
            )
        elif files_per_dir and depth < max_depth:
            # File previews happen only for top directories; we show up to N siblings.
            continue


def list_files(path: Path, limit: int, include_hidden: bool, ignore: set[str]) -> list[Path]:
    entries = list_directory(path)
    files: list[Path] = []
    for entry in entries:
        if entry.is_dir():
            continue
        if should_skip(entry, include_hidden=include_hidden, ignore=ignore):
            continue
        files.append(entry)
        if limit and len(files) >= limit:
            break
    return files


def describe_focus(
    base: Path,
    focus_path: Path,
    *,
    include_hidden: bool,
    ignore: set[str],
    files_per_dir: int,
    max_items: int,
) -> Iterator[str]:
    target = (base / focus_path).resolve()
    if not target.exists():
        yield f"[focus] {focus_path} — missing"
        return
    rel = os.path.relpath(target, base.resolve())
    yield f"[focus] {rel}/"
    entries = list_directory(target)
    visible_dirs = [
        entry
        for entry in entries
        if entry.is_dir() and not should_skip(entry, include_hidden=include_hidden, ignore=ignore)
    ]
    visible_files = list_files(
        target,
        limit=files_per_dir,
        include_hidden=include_hidden,
        ignore=ignore,
    )
    for entry in itertools.islice(visible_dirs, max_items):
        yield f"  - {entry.name}/"
        sub_files = list_files(
            entry,
            limit=files_per_dir,
            include_hidden=include_hidden,
            ignore=ignore,
        )
        for file_entry in sub_files:
            yield f"    • {file_entry.name}"
    if visible_files:
        yield "  files:"
        for file_entry in visible_files:
            yield f"    • {file_entry.name}"


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    ignore = DEFAULT_IGNORE | set(args.ignore or [])
    for line in walk_tree(
        root,
        depth=0,
        max_depth=max(0, args.max_depth),
        files_per_dir=args.files_per_dir,
        include_hidden=args.include_hidden,
        ignore=ignore,
        max_items=max(1, args.max_items),
    ):
        print(line)

    for focus in args.focus:
        print()
        for line in describe_focus(
            root,
            Path(focus),
            include_hidden=args.include_hidden,
            ignore=ignore,
            files_per_dir=args.files_per_dir,
            max_items=args.max_items,
        ):
            print(line)


if __name__ == "__main__":
    main()
