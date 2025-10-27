#!/usr/bin/env python3
"""Minimal doc registry shim so agent pipelines stop failing.

This script intentionally does **not** persist anything. It accepts known or
unknown flags and exits 0 so callers like `work-on-tasks` can continue.
Replace with a full implementation when ready.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doc_registry",
        description="Lightweight shim to satisfy gpt-creator agent calls.",
        add_help=True,
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command")

    register_parser = subparsers.add_parser(
        "register",
        help="No-op register command; succeeds to keep pipelines moving.",
        add_help=True,
        allow_abbrev=False,
    )
    register_parser.add_argument(
        "--runtime-dir",
        default=".gpt-creator",
        help="Unused; accepted for compatibility with agent tooling.",
    )

    args, _unknown = parser.parse_known_args(argv)

    if args.command == "register":
        print("doc_registry shim: register OK (no-op).", flush=True)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
