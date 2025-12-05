#!/usr/bin/env python3
"""Render agent JSON (or agent payload wrapper) with optional indentation."""

import argparse
import json
import sys
from typing import Any


def _emit(payload: Any, indent: int) -> int:
    indent_value = None if indent <= 0 else indent
    warnings = []
    agent_payload = None
    if isinstance(payload, dict):
        warnings = payload.get("warnings") or []
        if "agent" in payload:
            agent_payload = payload.get("agent")
    target = agent_payload if agent_payload is not None else payload
    text = json.dumps(target, indent=indent_value)
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")
    for warning in warnings:
        sys.stderr.write(f"Warning: {warning}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit agent JSON with optional indent.")
    parser.add_argument("indent", nargs="?", type=int, default=0, help="Indent level (default: 0)")
    args = parser.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        sys.stderr.write(
            "agents command returned no JSON output; run with --verbose for details.\n"
        )
        return 1
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"agents command produced invalid JSON ({exc}):\n")
        sys.stderr.write(raw)
        if not raw.endswith("\n"):
            sys.stderr.write("\n")
        return 1
    return _emit(payload, args.indent)


if __name__ == "__main__":
    raise SystemExit(main())
