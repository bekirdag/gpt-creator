#!/usr/bin/env python3
"""Extract the first valid JSON payload from a Codex transcript."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_SCAN_BYTES = 3_000_000
OPENERS = {"{": "}", "[": "]"}
CLOSERS = {v: k for k, v in OPENERS.items()}


def _load_payload(raw_path: Path) -> str:
    data = raw_path.read_text(encoding="utf-8", errors="replace")
    if len(data) > MAX_SCAN_BYTES:
        return data[:MAX_SCAN_BYTES]
    return data


def _first_json_fragment(payload: str) -> str | None:
    stack: list[str] = []
    start = -1
    in_string = False
    escape = False

    for idx, ch in enumerate(payload):
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch in OPENERS:
            if not stack:
                start = idx
            stack.append(ch)
            continue

        if ch in CLOSERS:
            if not stack:
                start = -1
                continue
            opener = stack.pop()
            if OPENERS[opener] != ch:
                stack.clear()
                start = -1
                continue
            if not stack and start != -1:
                fragment = payload[start : idx + 1]
                try:
                    json.loads(fragment)
                except json.JSONDecodeError:
                    start = -1
                    continue
                return fragment

    return None


def extract_json(raw_path: Path, out_path: Path) -> None:
    payload = _load_payload(raw_path)
    fragment = _first_json_fragment(payload)
    if fragment is None:
        raise SystemExit("Failed to locate JSON payload in Codex output")

    data = json.loads(fragment)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = parse_args(argv)
    extract_json(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
