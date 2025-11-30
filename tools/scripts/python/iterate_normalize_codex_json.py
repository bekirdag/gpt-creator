#!/usr/bin/env python3
"""Normalize Codex JSON output produced during `gpt-creator iterate`."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(1)

    raw_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    text = raw_path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(1)

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text)

    data = json.loads(text)
    if isinstance(data, list):
        data = {"tasks": data}
    elif "tasks" not in data:
        data = {"tasks": [data]}

    out_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
