#!/usr/bin/env python3
"""Extract offender configuration from a budget config JSON blob."""

import json
import sys


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: budget_offenders_from_config.py CONFIG_JSON")

    try:
        cfg = json.loads(argv[1])
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        offenders = {}
    else:
        offenders = cfg.get("offenders", {}) or {}
        if not isinstance(offenders, dict):
            offenders = {}
    print(json.dumps(offenders, separators=(",", ":"), ensure_ascii=True))


if __name__ == "__main__":
    main(sys.argv)
