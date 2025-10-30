#!/usr/bin/env python3
"""Append per-task phase usage metrics to the work-on-tasks NDJSON log."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict

PRODUCTIVE_STATUSES = {
    "complete",
    "complete-verified-no-diff",
    "completed-no-changes",
}

STATUS_ALIAS_MAP = {
    "completed": "complete",
}


def parse_points(text: str) -> float:
    cleaned = (text or "").strip()
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace(",", ".")
    for token in cleaned.split():
        try:
            value = float(token)
        except ValueError:
            continue
        if value > 0:
            return value
    return 0.0


def clamp_int(value: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(max(0, round(number)))


def normalize_status(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = cleaned.replace("_", "-").replace(" ", "-")
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = STATUS_ALIAS_MAP.get(cleaned, cleaned)
    return cleaned


def hotspot(tokens: Dict[str, int]) -> tuple[str, float]:
    total = sum(tokens.values())
    if total <= 0:
        return "", 0.0
    phase, value = max(tokens.items(), key=lambda item: item[1])
    if value <= 0:
        return "", 0.0
    return phase, value / total


def main() -> int:
    parser = argparse.ArgumentParser(description="Log per-task phase usage metrics.")
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--run-id", default="", help="Work-on-tasks run identifier.")
    parser.add_argument("--story", default="", help="Story slug.")
    parser.add_argument("--task-number", default="", help="Task number within the story (e.g. 005).")
    parser.add_argument("--task-id", default="", help="Canonical task identifier if available.")
    parser.add_argument("--status", default="", help="Final status string.")
    parser.add_argument("--story-points", default="", help="Story point value from the task metadata.")
    parser.add_argument("--tokens-retrieve", default="0")
    parser.add_argument("--tokens-plan", default="0")
    parser.add_argument("--tokens-patch", default="0")
    parser.add_argument("--tokens-verify", default="0")

    args = parser.parse_args()

    tokens = {
        "retrieve": clamp_int(args.tokens_retrieve),
        "plan": clamp_int(args.tokens_plan),
        "patch": clamp_int(args.tokens_patch),
        "verify": clamp_int(args.tokens_verify),
    }
    tokens_total = sum(tokens.values())

    status_norm = normalize_status(args.status)
    story_points = parse_points(args.story_points)
    delivered_sp = story_points if story_points > 0 and status_norm in PRODUCTIVE_STATUSES else 0.0
    tokens_per_sp = tokens_total / delivered_sp if delivered_sp > 0 else 0.0
    hotspot_phase, hotspot_share = hotspot(tokens)

    task_ref = args.task_id.strip() or f"{args.story}:{args.task_number}".strip(":")

    record = {
        "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "run_id": args.run_id,
        "story": args.story,
        "task": task_ref,
        "task_number": args.task_number,
        "final_status": status_norm,
        "tokens": tokens,
        "tokens_total": tokens_total,
        "tokens_per_sp": tokens_per_sp,
        "delivered_sp": delivered_sp,
        "hotspot_phase": hotspot_phase,
        "hotspot_share": hotspot_share,
    }

    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
