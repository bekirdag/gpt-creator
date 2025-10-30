#!/usr/bin/env python3
"""Emit offender data as tab-separated rows for shell consumption."""

import json
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: budget_offenders_iter.py OFFENDERS_JSON")

    try:
        cfg = json.loads(argv[1]) if argv[1] else {}
    except Exception:
        cfg = {}

    if not isinstance(cfg, dict):
        cfg = {}

    print(f"AUTO\t{int(bool(cfg.get('auto_abandon')))}")
    print(f"RUN\t{cfg.get('target_run_id', '')}")

    for item in cfg.get("stage_offenders", []):
        stage = item.get("stage")
        if not stage:
            continue
        total = int(item.get("total_tokens") or 0)
        limit = int(item.get("limit") or 0)
        print(f"STAGE\t{stage}\t{total}\t{limit}")

    for item in cfg.get("tool_offenders", []):
        tool = item.get("tool")
        if not tool:
            continue
        bytes_used = int(item.get("bytes") or 0)
        share = float(item.get("share") or 0.0)
        action = item.get("action") or ""
        print(f"TOOL\t{tool}\t{bytes_used}\t{share}\t{action}")


if __name__ == "__main__":
    main(sys.argv)
