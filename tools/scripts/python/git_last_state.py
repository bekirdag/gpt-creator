#!/usr/bin/env python3
"""Emit git-last metadata as key=value pairs for shell consumption."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FIELDS = ("branch", "merge", "base", "head", "changed")


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize(value) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return ""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Print git-last metadata.")
    parser.add_argument("state_file", help="Path to .gpt-creator/state/git-last.json")
    args = parser.parse_args(argv)
    state = load_state(Path(args.state_file))
    for field in FIELDS:
        print(f"{field}={normalize(state.get(field, ''))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
