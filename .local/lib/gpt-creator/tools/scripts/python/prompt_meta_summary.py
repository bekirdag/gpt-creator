#!/usr/bin/env python3
"""Summarise prompt metadata for work-on-tasks."""

import json
import sys
from pathlib import Path


def normalise_bool(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    if text in {"false", "0", "no", "off"}:
        return "false"
    return "true"


def main(argv):
    if len(argv) != 2:
        raise SystemExit("Usage: prompt_meta_summary.py PROMPT_META_PATH")

    path = Path(argv[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print("ok\t0\t0\ttrue\t0\t0\t{}\t0\tmissing\tinvalid-meta")
        return

    status = data.get("status") or "ok"
    soft = data.get("token_budget_soft") or 0
    hard = data.get("token_budget_hard") or 0
    stop = normalise_bool(data.get("stop_on_overbudget"))
    estimate = data.get("token_estimate_final") or 0
    pruned = data.get("pruned") or {}
    pruned_bytes = pruned.get("bytes") or 0
    pruned_items = pruned.get("items") or {}
    reserved = data.get("reserved_output") or 0
    binder = data.get("binder") or {}
    binder_status = binder.get("status") or ""
    binder_reason = binder.get("reason") or ""

    print(
        f"{status}\t{soft}\t{hard}\t{stop}\t{estimate}\t{pruned_bytes}\t"
        + json.dumps(pruned_items, separators=(",", ":"))
        + f"\t{reserved}\t{binder_status}\t{binder_reason}"
    )


if __name__ == "__main__":
    main(sys.argv)
