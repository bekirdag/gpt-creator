#!/usr/bin/env python3
"""Generate per-run budget report markdown."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Produce budget-report.md")
    parser.add_argument("--usage-file", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--stage-limits", default="{}")
    parser.add_argument("--tool-actions", default="{}")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def load_entries(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload


def summarise_pruned(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key, data in value.items():
            if isinstance(data, dict):
                count = data.get("count")
                bytes_ = data.get("bytes")
                if isinstance(count, int) and isinstance(bytes_, int):
                    parts.append(f"{key}:{count} ({bytes_} bytes)")
                elif isinstance(count, int):
                    parts.append(f"{key}:{count}")
                elif isinstance(bytes_, int):
                    parts.append(f"{key}:{bytes_} bytes")
                else:
                    parts.append(f"{key}")
            else:
                parts.append(f"{key}:{data}")
        return ", ".join(parts) if parts else "—"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "—"
    if value in (None, "", []):
        return "—"
    return str(value)


def format_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens/1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens/1_000:.1f}K"
    return str(tokens)


def format_duration(ms: int) -> str:
    if ms <= 0:
        return "—"
    seconds = ms / 1000.0
    return f"{seconds:.1f}s"


def build_report(entries: Iterable[Dict[str, Any]], run_id: str, stage_limits: Dict[str, int], tool_actions: Dict[str, str]) -> str:
    stage_summary: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"tokens": 0, "duration": 0, "blocked": False, "pruned": []})
    tool_totals: Dict[str, int] = defaultdict(int)

    for entry in entries:
        if str(entry.get("run_id") or "") != run_id:
            continue
        stage = str(entry.get("stage") or "")
        if not stage:
            continue
        summary = stage_summary[stage]
        summary["tokens"] += int(entry.get("total_tokens") or 0)
        summary["duration"] += int(entry.get("duration_ms") or 0)
        if entry.get("blocked_quota"):
            summary["blocked"] = True
        summary["pruned"].append(entry.get("pruned_items"))
        tool_bytes = entry.get("tool_bytes")
        if isinstance(tool_bytes, dict):
            for tool, value in tool_bytes.items():
                try:
                    tool_totals[str(tool)] += int(value)
                except (TypeError, ValueError):
                    pass

    if not stage_summary:
        return f"# Budget Report (Run {run_id})\n\nNo telemetry captured for this run.\n"

    lines: List[str] = []
    lines.append(f"# Budget Report (Run {run_id})")
    lines.append("")
    lines.append("| Stage | Tokens | Duration | Pruned | Status |")
    lines.append("| --- | ---: | ---: | --- | --- |")
    for stage in sorted(stage_summary.keys()):
        data = stage_summary[stage]
        total_tokens = int(data["tokens"])
        duration = int(data["duration"])
        pruned_entries = data["pruned"]
        pruned_text = summarise_pruned(pruned_entries[-1] if pruned_entries else None)
        limit = stage_limits.get(stage)
        offender_text = "over limit" if (limit and total_tokens > int(limit)) else ("blocked" if data["blocked"] else "")
        lines.append(
            f"| {stage} | {format_tokens(total_tokens)} | {format_duration(duration)} | {pruned_text} | {offender_text or '—'} |"
        )

    if tool_totals:
        lines.append("")
        lines.append("## Top Burners")
        total_bytes = sum(tool_totals.values())
        ranked = sorted(tool_totals.items(), key=lambda item: item[1], reverse=True)[:3]
        for idx, (tool, amount) in enumerate(ranked, start=1):
            share = (amount / total_bytes * 100) if total_bytes else 0.0
            action = tool_actions.get(tool)
            action_text = f" • remedy: {action}" if action else ""
            lines.append(f"{idx}. `{tool}` — {amount} bytes ({share:.1f}%) {action_text}")
    else:
        lines.append("")
        lines.append("## Top Burners\nNo tool telemetry recorded for this run.")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    usage_path = Path(args.usage_file)
    stage_limits = json.loads(args.stage_limits)
    if not isinstance(stage_limits, dict):
        stage_limits = {}
    tool_actions = json.loads(args.tool_actions)
    if not isinstance(tool_actions, dict):
        tool_actions = {}

    report = build_report(load_entries(usage_path), args.run_id, stage_limits, tool_actions)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
