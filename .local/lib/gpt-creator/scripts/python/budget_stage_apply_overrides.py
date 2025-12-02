#!/usr/bin/env python3
"""Apply stage limit overrides to a per-stage limits JSON blob."""

import json
import sys


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit(
            "Usage: budget_stage_apply_overrides.py STAGE_JSON [stage=value ...]"
        )

    try:
        stage_cfg = json.loads(argv[1]) if argv[1] else {}
    except Exception:
        stage_cfg = {}
    if not isinstance(stage_cfg, dict):
        stage_cfg = {}

    for raw in argv[2:]:
        if not raw or "=" not in raw:
            continue
        stage, value = raw.split("=", 1)
        stage = stage.strip()
        value = value.strip()
        if not stage or not value.isdigit():
            continue
        stage_cfg[stage] = int(value)

    print(json.dumps(stage_cfg, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main(sys.argv)
