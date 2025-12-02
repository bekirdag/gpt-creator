#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

MAX_SCAN_BYTES = 2_000_000  # hard guard so pathological outputs cannot exhaust memory


def extract_first_object(payload: str) -> str | None:
    """Return the first syntactically valid JSON object substring or None."""
    depth = 0
    in_string = False
    escape = False
    start = -1

    for idx, ch in enumerate(payload):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            if depth == 0 and start == -1:
                # strings before the object should be ignored
                continue
        elif ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth == 0:
                # unmatched closing brace; reset
                start = -1
                continue
            depth -= 1
            if depth == 0 and start != -1:
                candidate = payload[start : idx + 1]
                try:
                    json.loads(candidate)
                except Exception:
                    start = -1
                    continue
                return candidate
    return None


def main() -> int:
    data = sys.stdin.read(MAX_SCAN_BYTES + 1)
    if len(data) > MAX_SCAN_BYTES:
        data = data[:MAX_SCAN_BYTES]
    fragment = extract_first_object(data)
    if fragment is None:
        sys.stderr.write("E: no JSON object detected in Codex output\n")
        return 3
    sys.stdout.write(fragment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
