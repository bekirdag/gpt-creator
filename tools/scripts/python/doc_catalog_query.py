#!/usr/bin/env python3
"""Friendly wrapper around doc_catalog.py to avoid unsupported flags."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _default_doc_catalog_script() -> Path:
    env_value = os.environ.get("GC_DOC_CATALOG_PY")
    if env_value:
        return Path(env_value)
    return Path(__file__).resolve().parent / "doc_catalog.py"


def _default_db_path() -> Path | None:
    env_value = os.environ.get("GC_DOCUMENTATION_DB_PATH")
    if env_value:
        return Path(env_value)
    return None


def _run_doc_catalog(args_list: list[str]) -> int:
    script = _default_doc_catalog_script()
    if not script.exists():
        print(f"doc_catalog script not found at {script}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(script), *args_list]
    proc = subprocess.run(cmd, text=True)
    return proc.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the documentation catalog with supported flags only.")
    parser.add_argument(
        "--db",
        default=None,
        help="Path to documentation catalog DB (defaults to GC_DOCUMENTATION_DB_PATH).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cmd = subparsers.add_parser("list", help="List documents recently added to the catalog.")
    list_cmd.add_argument("--limit", type=int, default=10, help="Result limit (default: 10)")

    search = subparsers.add_parser("search", help="Search documents by term.")
    search.add_argument("query", help="Search term")
    search.add_argument("--limit", type=int, default=5, help="Result limit (default: 5)")

    show = subparsers.add_parser("show", help="Show a slice of a document by doc-id")
    show.add_argument("doc_id", help="Catalog doc id (e.g., DOC-1234ABCD)")
    show.add_argument("--start", type=int, default=None, help="Start line (default per doc_catalog)")
    show.add_argument("--end", type=int, default=None, help="End line (default per doc_catalog)")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db) if args.db else _default_db_path()
    base_args: list[str] = []
    if db_path is not None:
        base_args.extend(["--db", str(db_path)])
    if args.command == "list":
        cmd_args = ["list", "--limit", str(args.limit)]
    elif args.command == "search":
        cmd_args = ["search", "--query", args.query, "--limit", str(args.limit)]
    else:
        cmd_args = ["show", "--doc-id", args.doc_id]
        if args.start is not None:
            cmd_args.extend(["--start", str(args.start)])
        if args.end is not None:
            cmd_args.extend(["--end", str(args.end)])
    return _run_doc_catalog(base_args + cmd_args)


if __name__ == "__main__":
    raise SystemExit(main())
