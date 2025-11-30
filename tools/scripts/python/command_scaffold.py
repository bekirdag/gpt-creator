#!/usr/bin/env python3
"""Helper to scaffold fully formed `bash -lc` commands for work-on-tasks."""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import List


def build_command(description: str, steps: List[str]) -> str:
    quoted_steps = []
    for step in steps:
        trimmed = step.strip()
        if not trimmed:
            continue
        quoted_steps.append(trimmed)
    if not quoted_steps:
        raise ValueError("At least one command fragment is required")
    joined = " && ".join(quoted_steps)
    return f"bash -lc \"{joined}\""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a placeholder-free bash command for work-on-tasks.",
    )
    parser.add_argument(
        "description",
        help="Short label for the command block (e.g., 'seed contact fixtures').",
    )
    parser.add_argument(
        "steps",
        nargs="+",
        help="One or more shell fragments to chain with && (e.g., 'cd apps/api', 'pnpm test').",
    )
    parser.add_argument(
        "--print-label",
        action="store_true",
        help="Also print an Action/Result note referencing the description.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        command = build_command(args.description, args.steps)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(command)
    if args.print_label:
        escaped = shlex.quote(args.description)
        print(f"Action: command:{args.description} | Result: prepared {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
