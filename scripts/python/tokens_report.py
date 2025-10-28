#!/usr/bin/env python3
"""Summarise Codex usage logs for the `gpt-creator tokens` command."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    cleaned = value
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def isoformat(dt: datetime | None) -> str:
    if dt is None:
        return ""
    text = dt.isoformat()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def clamp(text: str | None, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def fmt_int(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def fmt_exit_code(value: object) -> str:
    parsed = as_int(value)
    if parsed is None:
        return "-"
    return str(parsed)


def load_records(path: Path) -> tuple[list[dict[str, object]], int]:
    raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    records: list[dict[str, object]] = []
    captured_count = 0
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        records.append(payload)
        if payload.get("usage_captured"):
            captured_count += 1
    return records, captured_count


def build_summary(records: list[dict[str, object]], captured: int) -> tuple[dict[str, object], list[dict[str, object]]]:
    fields = (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
        "billable_units",
        "request_units",
    )
    totals = {field: 0 for field in fields}
    counts = {field: 0 for field in fields}

    for entry in records:
        for field in fields:
            value = as_int(entry.get(field))
            if value is not None:
                totals[field] += value
                counts[field] += 1

    timestamps = [ts for ts in (parse_timestamp(rec.get("timestamp")) for rec in records) if ts is not None]
    first_ts = isoformat(min(timestamps)) if timestamps else ""
    last_ts = isoformat(max(timestamps)) if timestamps else ""

    summary: dict[str, object] = {
        "entries": len(records),
        "captured_entries": captured,
        "totals": {field: totals[field] for field in fields if counts[field]},
    }
    if first_ts:
        summary["first_timestamp"] = first_ts
    if last_ts:
        summary["last_timestamp"] = last_ts

    sorted_records = sorted(records, key=lambda rec: rec.get("timestamp") or "")
    return summary, sorted_records


def print_table(rows: list[list[str]]) -> None:
    headers = ["timestamp", "task", "model", "total", "prompt", "completion", "cached", "billable", "request", "exit", "captured"]
    widths: list[int] = []
    for index, header in enumerate(headers):
        column_values = [len(header)] + [len(row[index]) for row in rows]
        widths.append(max(column_values))

    print()
    header_line = "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
    separator = "  ".join("-" * widths[i] for i in range(len(headers)))
    print(header_line)
    print(separator)
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(1)

    usage_path = Path(sys.argv[1])
    details = sys.argv[2] == "1"
    json_mode = sys.argv[3] == "1"

    records, captured = load_records(usage_path)
    if not records:
        print("No usage entries recorded.")
        raise SystemExit(0)

    summary, sorted_records = build_summary(records, captured)
    first_ts = summary.get("first_timestamp", "")
    last_ts = summary.get("last_timestamp", "")

    if json_mode:
        payload = dict(summary)
        if details:
            rows = []
            for rec in sorted_records:
                rows.append(
                    {
                        "timestamp": rec.get("timestamp"),
                        "task": rec.get("task"),
                        "model": rec.get("model"),
                        "prompt_tokens": as_int(rec.get("prompt_tokens")),
                        "completion_tokens": as_int(rec.get("completion_tokens")),
                        "total_tokens": as_int(rec.get("total_tokens")),
                        "cached_tokens": as_int(rec.get("cached_tokens")),
                        "billable_units": as_int(rec.get("billable_units")),
                        "request_units": as_int(rec.get("request_units")),
                        "exit_code": as_int(rec.get("exit_code")),
                        "usage_captured": bool(rec.get("usage_captured")),
                    }
                )
            payload["rows"] = rows
        print(json.dumps(payload, indent=2))
        raise SystemExit(0)

    print(f"Codex usage file: {usage_path}")
    print(f"Entries: {summary['entries']} (captured={summary['captured_entries']})")
    if first_ts and last_ts:
        print(f"Range: {first_ts} → {last_ts}")

    label_map = {
        "prompt_tokens": "Prompt tokens",
        "completion_tokens": "Completion tokens",
        "total_tokens": "Total tokens",
        "cached_tokens": "Cached tokens",
        "billable_units": "Billable units",
        "request_units": "Request units",
    }

    totals = summary["totals"]  # type: ignore[assignment]
    for field, label in label_map.items():
        if field in totals:
            print(f"{label}: {totals[field]:,}")  # type: ignore[index]

    if not details:
        raise SystemExit(0)

    rows = []
    for rec in sorted_records:
        rows.append(
            [
                rec.get("timestamp") or "",
                clamp(rec.get("task") or "", 32),
                clamp(rec.get("model") or "", 24),
                fmt_int(as_int(rec.get("total_tokens"))),
                fmt_int(as_int(rec.get("prompt_tokens"))),
                fmt_int(as_int(rec.get("completion_tokens"))),
                fmt_int(as_int(rec.get("cached_tokens"))),
                fmt_int(as_int(rec.get("billable_units"))),
                fmt_int(as_int(rec.get("request_units"))),
                fmt_exit_code(rec.get("exit_code")),
                "yes" if rec.get("usage_captured") else "no",
            ]
        )

    print_table(rows)


if __name__ == "__main__":
    main()
