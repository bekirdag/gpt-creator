#!/usr/bin/env python3
"""Summarize guardrail events for CI/dashboards."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, Tuple


def iter_events(path: Path) -> Iterable[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize guardrail telemetry events.")
    parser.add_argument(
        "--file",
        default="logs/guardrails/events.jsonl",
        help="Path to the guardrail events JSONL file (default: %(default)s).",
    )
    parser.add_argument(
        "--fail-on-placeholder",
        type=int,
        default=None,
        help="Exit with failure if commands-placeholder-detected count >= this threshold.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON summary instead of human-readable text.",
    )
    args = parser.parse_args()

    path = Path(args.file)
    counts: Counter[str] = Counter()
    by_run: Dict[str, Counter[str]] = defaultdict(Counter)
    for event in iter_events(path):
        code = str(event.get("code") or "unknown")
        counts[code] += 1
        run = str(event.get("run") or "(unknown-run)")
        by_run[run][code] += 1

    summary = {
        "total_events": sum(counts.values()),
        "by_code": dict(counts),
        "runs": {run: dict(counter) for run, counter in by_run.items()},
    }

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print("Guardrail events summary:")
        for code, count in sorted(counts.items()):
            print(f"- {code}: {count}")
        print("")
        for run, counter in sorted(by_run.items()):
            details = ", ".join(f"{code}={count}" for code, count in sorted(counter.items()))
            print(f"Run {run}: {details}")

    threshold = args.fail_on_placeholder
    if threshold is not None:
        placeholder_hits = counts.get("commands-placeholder-detected", 0)
        if placeholder_hits >= threshold:
            print(
                f"commands-placeholder-detected count {placeholder_hits} exceeds threshold {threshold}; failing",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
