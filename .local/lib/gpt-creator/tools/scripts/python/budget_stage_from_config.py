#!/usr/bin/env python3
"""Extract per-stage limits from a budget configuration JSON blob."""

import json
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: budget_stage_from_config.py CONFIG_JSON")

    try:
        cfg = json.loads(argv[1])
    except Exception:
        cfg = {}

    if not isinstance(cfg, dict):
        stage_limits = {}
    else:
        stage_limits = cfg.get("per_stage_limits", {}) or {}
        if not isinstance(stage_limits, dict):
            stage_limits = {}

    print(json.dumps(stage_limits, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main(sys.argv)
