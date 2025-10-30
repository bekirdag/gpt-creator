#!/usr/bin/env python3
"""Update verify summary JSON and emit event data."""

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any


def relify(path_value: str, project_root: str) -> str:
    if not path_value:
        return ""
    candidate = Path(path_value)
    if not candidate.is_absolute() and project_root:
        candidate = (Path(project_root) / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if project_root:
        try:
            rel = candidate.relative_to(project_root)
        except Exception:
            rel = candidate
    else:
        rel = candidate
    return str(rel).replace(os.sep, "/")


def parse_float(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except Exception:
        return None


def parse_timestamp(value: str | None) -> str:
    if value:
        return value
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def main(argv: list[str]) -> None:
    if len(argv) < 6:
        raise SystemExit(
            "Usage: update_verify_summary.py SUMMARY_PATH PROJECT_ROOT ORDER "
            "NAME STATUS [LABEL] [MESSAGE] [LOG] [REPORT] [SCORE] [DURATION] [RUN_KIND] [TIMESTAMP]"
        )

    summary_path = Path(argv[1])
    project_root = argv[2]
    check_order = argv[3]
    name = argv[4]
    status = argv[5] if len(argv) > 5 else "unknown"
    label = argv[6] if len(argv) > 6 else (name.title() if name else "")
    message = argv[7] if len(argv) > 7 else ""
    log_path = argv[8] if len(argv) > 8 else ""
    report_path = argv[9] if len(argv) > 9 else ""
    score_raw = argv[10] if len(argv) > 10 else ""
    duration_raw = argv[11] if len(argv) > 11 else ""
    run_kind = argv[12] if len(argv) > 12 else ""
    timestamp = parse_timestamp(argv[13] if len(argv) > 13 else "")

    if not name:
        raise SystemExit(0)

    try:
        if summary_path.exists():
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        else:
            data = {}
    except Exception:
        data = {}

    checks = data.get("checks")
    if not isinstance(checks, dict):
        checks = {}

    entry: Dict[str, Any] = checks.get(name, {})
    entry["name"] = name
    entry["label"] = label or name.title()
    entry["status"] = status

    if message:
        entry["message"] = message
    else:
        entry.pop("message", None)

    log_rel = relify(log_path, project_root)
    if log_rel:
        entry["log"] = log_rel
    else:
        entry.pop("log", None)

    report_rel = relify(report_path, project_root)
    if report_rel:
        entry["report"] = report_rel
    else:
        entry.pop("report", None)

    score_value = parse_float(score_raw)
    if score_value is not None:
        entry["score"] = score_value
    else:
        entry.pop("score", None)

    duration_value = parse_float(duration_raw)
    if duration_value is not None:
        entry["duration_seconds"] = duration_value
    else:
        entry.pop("duration_seconds", None)

    entry["updated"] = timestamp
    if run_kind:
        entry["run_kind"] = run_kind
    else:
        entry.pop("run_kind", None)

    checks[name] = entry
    data["checks"] = checks
    data["last_updated"] = timestamp
    if run_kind:
        data["last_run_kind"] = run_kind

    stats = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
    for chk in checks.values():
        status_value = str(chk.get("status", "")).lower()
        if status_value in {"pass", "passed", "ok", "success"}:
            stats["passed"] += 1
        elif status_value in {"skip", "skipped"}:
            stats["skipped"] += 1
        else:
            stats["failed"] += 1
        stats["total"] += 1
    data["stats"] = stats

    order_tokens = [part.strip() for part in (check_order or "").split(",") if part.strip()]
    if order_tokens:
        merged = []
        seen = set()
        for item in order_tokens:
            if item not in seen:
                merged.append(item)
                seen.add(item)
        for item in checks.keys():
            if item not in seen:
                merged.append(item)
                seen.add(item)
        data["order"] = merged
    else:
        existing = data.get("order")
        merged = []
        seen = set()
        if isinstance(existing, list):
            for item in existing:
                if isinstance(item, str) and item not in seen:
                    merged.append(item)
                    seen.add(item)
        for item in checks.keys():
            if item not in seen:
                merged.append(item)
                seen.add(item)
        data["order"] = merged

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    event = {
        "name": name,
        "label": entry.get("label", label),
        "status": status,
        "message": entry.get("message", ""),
        "log": entry.get("log", ""),
        "report": entry.get("report", ""),
        "score": entry.get("score"),
        "updated": timestamp,
        "run_kind": entry.get("run_kind", run_kind),
        "stats": stats,
        "duration_seconds": entry.get("duration_seconds"),
    }
    print(json.dumps(event, separators=(",", ":")))


if __name__ == "__main__":
    main(sys.argv)
