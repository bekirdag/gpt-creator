#!/usr/bin/env python3
"""Summarise offender configuration meta values."""

import json
import sys


def as_int(value, fallback):
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return fallback
    return iv if iv > 0 else fallback


def as_float(value, fallback):
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return fallback
    return fv if 0.0 < fv <= 1.0 else fallback


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: budget_offenders_meta.py OFFENDERS_JSON")

    try:
        cfg = json.loads(argv[1]) if argv[1] else {}
    except Exception:
        cfg = {}

    if not isinstance(cfg, dict):
        cfg = {}

    window = as_int(cfg.get("window_runs", 10), 10)
    top_k = as_int(cfg.get("top_k", 3), 3)
    dominance = as_float(cfg.get("dominance_threshold", 0.5), 0.5)
    auto_flag = to_bool(cfg.get("auto_abandon", True))
    actions = cfg.get("actions", {})
    if not isinstance(actions, dict):
        actions = {}

    print(
        f"{window}\t{top_k}\t{dominance}\t{int(auto_flag)}\t"
        + json.dumps(actions, separators=(",", ":"), ensure_ascii=True)
    )


if __name__ == "__main__":
    main(sys.argv)
