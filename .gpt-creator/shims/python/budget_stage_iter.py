#!/usr/bin/env python3
"""Emit per-stage limits as tab-separated records."""

import json
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: budget_stage_iter.py STAGE_JSON")

    try:
        stage_cfg = json.loads(argv[1]) if argv[1] else {}
    except Exception:
        stage_cfg = {}

    if not isinstance(stage_cfg, dict):
        stage_cfg = {}

    for name, value in stage_cfg.items():
        try:
            limit = int(value)
        except (TypeError, ValueError):
            continue
        print(f"{name}\t{limit}")


if __name__ == "__main__":
    main(sys.argv)
