#!/usr/bin/env python3
"""Summarise adapter usage logs for the `gpt-creator tokens` command."""

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


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return False


TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "prompt_tokens": ("prompt_tokens", "tokens_in", "prompt", "input_tokens"),
    "completion_tokens": ("completion_tokens", "tokens_out", "completion", "output_tokens"),
    "total_tokens": ("total_tokens", "token_count", "tokens_total", "total"),
    "cached_tokens": ("cached_tokens",),
    "billable_units": ("billable_units",),
    "request_units": ("request_units",),
}


def first_int(entry: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        if key not in entry:
            continue
        value = as_int(entry.get(key))
        if value is not None:
            return value
    return None


def load_records(path: Path) -> tuple[list[dict[str, object]], int]:
    if not path.exists():
        return [], 0
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
        if truthy(payload.get("usage_captured")):
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
            aliases = TOKEN_ALIASES.get(field, (field,))
            value = first_int(entry, *aliases)
            if field == "total_tokens" and value is None:
                prompt_val = first_int(entry, *TOKEN_ALIASES["prompt_tokens"])
                completion_val = first_int(entry, *TOKEN_ALIASES["completion_tokens"])
                if prompt_val is not None or completion_val is not None:
                    value = (prompt_val or 0) + (completion_val or 0)
            if value is not None:
                totals[field] += value
                counts[field] += 1

    timestamps = [ts for ts in (parse_timestamp(rec.get("timestamp") or rec.get("ts")) for rec in records) if ts is not None]
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

    sorted_records = sorted(records, key=lambda rec: rec.get("timestamp") or rec.get("ts") or "")
    return summary, sorted_records


def print_table(rows: list[list[str]]) -> None:
    headers = [
        "timestamp",
        "adapter",
        "task",
        "stage",
        "model",
        "total",
        "tokens_in",
        "tokens_out",
        "cached",
        "billable",
        "request",
        "exit",
        "captured",
    ]
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
        raise SystemExit("usage: tokens_report.py <usage_path> <details 0|1> <json 0|1>")

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
                prompt_val = first_int(rec, *TOKEN_ALIASES["prompt_tokens"])
                completion_val = first_int(rec, *TOKEN_ALIASES["completion_tokens"])
                total_val = first_int(rec, *TOKEN_ALIASES["total_tokens"])
                if total_val is None and (prompt_val is not None or completion_val is not None):
                    total_val = (prompt_val or 0) + (completion_val or 0)
                rows.append(
                    {
                        "timestamp": rec.get("timestamp") or rec.get("ts"),
                        "run_id": rec.get("run_id"),
                        "task": rec.get("task"),
                        "stage": rec.get("stage") or rec.get("step"),
                        "adapter": rec.get("adapter"),
                        "model": rec.get("model"),
                        "prompt_tokens": prompt_val,
                        "completion_tokens": completion_val,
                        "total_tokens": total_val,
                        "cached_tokens": first_int(rec, *TOKEN_ALIASES["cached_tokens"]),
                        "billable_units": first_int(rec, *TOKEN_ALIASES["billable_units"]),
                        "request_units": first_int(rec, *TOKEN_ALIASES["request_units"]),
                        "exit_code": as_int(rec.get("exit_code") or rec.get("exit")),
                        "usage_captured": truthy(rec.get("usage_captured")),
                    }
                )
            payload["rows"] = rows
        print(json.dumps(payload, indent=2))
        raise SystemExit(0)

    print(f"Usage file: {usage_path}")
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
        adapter = rec.get("adapter") or ""
        stage = rec.get("stage") or rec.get("step") or ""
        timestamp_value = rec.get("timestamp") or rec.get("ts") or ""
        prompt_val = first_int(rec, *TOKEN_ALIASES["prompt_tokens"])
        completion_val = first_int(rec, *TOKEN_ALIASES["completion_tokens"])
        total_val = first_int(rec, *TOKEN_ALIASES["total_tokens"])
        if total_val is None and (prompt_val is not None or completion_val is not None):
            total_val = (prompt_val or 0) + (completion_val or 0)
        cached_val = first_int(rec, *TOKEN_ALIASES["cached_tokens"])
        billable_val = first_int(rec, *TOKEN_ALIASES["billable_units"])
        request_val = first_int(rec, *TOKEN_ALIASES["request_units"])
        rows.append(
            [
                timestamp_value,
                clamp(adapter, 16),
                clamp(rec.get("task") or "", 32),
                clamp(stage or "", 16),
                clamp(rec.get("model") or "", 24),
                fmt_int(total_val),
                fmt_int(prompt_val),
                fmt_int(completion_val),
                fmt_int(cached_val),
                fmt_int(billable_val),
                fmt_int(request_val),
                fmt_exit_code(rec.get("exit_code") or rec.get("exit")),
                "yes" if truthy(rec.get("usage_captured")) else "no",
            ]
        )

    print_table(rows)


if __name__ == "__main__":
    main()
