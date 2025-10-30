#!/usr/bin/env python3
"""Append budget stage telemetry entries in NDJSON format."""

import json
import sys
from pathlib import Path


def parse_int(value: str) -> int:
    try:
        return int(float(value or "0"))
    except (TypeError, ValueError):
        return 0


def parse_json(data: str, fallback):
    if not data:
        return fallback
    try:
        return json.loads(data)
    except Exception:
        return fallback


def main(argv: list[str]) -> None:
    if len(argv) < 12:
        raise SystemExit(
            "Usage: gc_budget_log_stage.py USAGE_PATH TS RUN_ID STORY TASK STAGE MODEL "
            "PROMPT COMPLETION TOTAL DURATION [PRUNED] [TOOLS] [BLOCKED] [NOTE]"
        )

    usage_path = Path(argv[1])
    ts, run_id, story, task, stage, model = argv[2:8]
    prompt_tokens = parse_int(argv[8])
    completion_tokens = parse_int(argv[9])
    total_tokens = parse_int(argv[10])
    duration_ms = parse_int(argv[11])
    pruned_raw = argv[12] if len(argv) > 12 else "[]"
    tool_raw = argv[13] if len(argv) > 13 else "{}"
    blocked_raw = argv[14] if len(argv) > 14 else "false"
    note = argv[15] if len(argv) > 15 else ""

    pruned_items = parse_json(pruned_raw, [])
    tool_bytes = parse_json(tool_raw, {})
    blocked_flag = str(blocked_raw).strip().lower() in {"1", "true", "yes", "on"}

    record = {
        "ts": ts,
        "run_id": run_id,
        "story": story,
        "task": task,
        "stage": stage,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "duration_ms": duration_ms,
        "pruned_items": pruned_items,
        "tool_bytes": tool_bytes,
        "blocked_quota": blocked_flag,
    }
    if note:
        record["note"] = note

    try:
        with usage_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"[warn] Failed to append stage telemetry: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv)
