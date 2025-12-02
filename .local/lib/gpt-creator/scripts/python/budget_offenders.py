#!/usr/bin/env python3
"""
Analyse recent codex usage telemetry and surface stage/tool offenders.

Outputs JSON describing which stages exceeded configured limits in the
most recent run and which tools dominated token/byte usage.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect budget offenders.")
    parser.add_argument("--usage-file", default=".gpt-creator/logs/codex-usage.ndjson")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--window-runs", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--dominance-threshold", type=float, default=0.5)
    parser.add_argument("--actions-json", default="{}")
    parser.add_argument("--per-stage-json", default="{}")
    parser.add_argument("--auto-abandon", action="store_true")
    parser.add_argument("--no-auto-abandon", action="store_true")
    return parser.parse_args()


def load_usage(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def parse_timestamp(value: Any) -> Tuple[int, str]:
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(dt.timestamp()), value
        except ValueError:
            pass
    return 0, str(value or "")


def group_by_run(entries: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    runs: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        run_id = str(entry.get("run_id") or "manual")
        ts_val, ts_raw = parse_timestamp(entry.get("ts"))
        stage = str(entry.get("stage") or "")
        total_tokens = int(entry.get("total_tokens") or 0)
        tool_bytes = entry.get("tool_bytes") or {}
        if run_id not in runs:
            runs[run_id] = {
                "ts": ts_val,
                "ts_raw": ts_raw,
                "stages": defaultdict(int),
                "tools": defaultdict(int),
            }
        bucket = runs[run_id]
        if ts_val > bucket["ts"]:
            bucket["ts"] = ts_val
            bucket["ts_raw"] = ts_raw
        if stage:
            bucket["stages"][stage] += total_tokens
        if isinstance(tool_bytes, dict):
            for tool, value in tool_bytes.items():
                try:
                    amount = int(value)
                except (TypeError, ValueError):
                    continue
                bucket["tools"][str(tool)] += amount
    return runs


def detect_stage_offenders(latest: Dict[str, Any], limits: Dict[str, int]) -> List[Dict[str, Any]]:
    offenders: List[Dict[str, Any]] = []
    stage_totals: Dict[str, int] = latest.get("stages", {})  # type: ignore[assignment]
    for stage, limit in limits.items():
        if limit <= 0:
            continue
        actual = int(stage_totals.get(stage, 0))
        if actual > limit:
            offenders.append({"stage": stage, "total_tokens": actual, "limit": limit})
    return offenders


def detect_tool_offenders(
    latest: Dict[str, Any],
    top_k: int,
    dominance: float,
    actions: Dict[str, str],
) -> List[Dict[str, Any]]:
    offenders: List[Dict[str, Any]] = []
    tool_totals: Dict[str, int] = latest.get("tools", {})  # type: ignore[assignment]
    if not tool_totals:
        return offenders
    total_bytes = sum(max(0, int(val)) for val in tool_totals.values())
    if total_bytes <= 0:
        return offenders
    ranked = sorted(
        ((tool, max(0, int(val))) for tool, val in tool_totals.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    for tool, bytes_used in ranked[: max(1, top_k)]:
        share = bytes_used / total_bytes
        if share >= dominance:
            offenders.append(
                {
                    "tool": tool,
                    "bytes": bytes_used,
                    "share": share,
                    "action": actions.get(tool),
                }
            )
    return offenders


def main() -> int:
    args = parse_args()
    usage_entries = load_usage(Path(args.usage_file).resolve())
    runs = group_by_run(usage_entries)
    if not runs:
        print(
            json.dumps(
                {
                    "stage_offenders": [],
                    "tool_offenders": [],
                    "target_run_id": "",
                    "auto_abandon": args.auto_abandon and not args.no_auto_abandon,
                }
            )
        )
        return 0

    sorted_runs = sorted(
        runs.items(),
        key=lambda item: (item[1]["ts"], item[0]),
    )
    target_run_id = args.run_id or (sorted_runs[-1][0] if sorted_runs else "")
    latest = runs.get(target_run_id) or sorted_runs[-1][1]

    try:
        stage_limits = json.loads(args.per_stage_json) if args.per_stage_json else {}
    except json.JSONDecodeError:
        stage_limits = {}
    if not isinstance(stage_limits, dict):
        stage_limits = {}
    stage_limits = {str(k): int(v) for k, v in stage_limits.items() if isinstance(v, (int, float))}

    try:
        actions_map = json.loads(args.actions_json) if args.actions_json else {}
    except json.JSONDecodeError:
        actions_map = {}
    if not isinstance(actions_map, dict):
        actions_map = {}
    actions_map = {str(k): str(v) for k, v in actions_map.items()}

    stage_offenders = detect_stage_offenders(latest, stage_limits)
    tool_offenders = detect_tool_offenders(
        latest,
        top_k=args.top_k,
        dominance=args.dominance_threshold,
        actions=actions_map,
    )

    auto_abandon = args.auto_abandon and not args.no_auto_abandon

    output = {
        "stage_offenders": stage_offenders,
        "tool_offenders": tool_offenders,
        "target_run_id": target_run_id,
        "auto_abandon": auto_abandon,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
