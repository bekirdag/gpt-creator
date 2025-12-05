#!/usr/bin/env python3
"""Parse registry validation JSON into newline-separated hints."""

import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    raw = sys.argv[1]
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    print(data.get("adapter", ""))
    print(data.get("maxContextTokens") or "")
    print(data.get("maxOutputTokens") or "")
    print(data.get("apiBase") or "")
    print(data.get("apiKeyEnv") or "")
    print(data.get("orgEnv") or "")
    print(data.get("apiBaseEnv") or "")
    print(data.get("model") or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
