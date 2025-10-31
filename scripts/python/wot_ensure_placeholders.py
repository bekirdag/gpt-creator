#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ALLOWED_EXT = (".md", ".csv", ".json", ".sql", ".txt", ".ics")


def main(path: str) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    desired = set()
    for change in data.get("changes") or []:
        if isinstance(change, dict) and "path" in change:
            if "contents" in change or "contents_path" in change:
                desired.add(change["path"])
    for candidate in sorted(desired):
        if candidate.endswith(ALLOWED_EXT) and not Path(candidate).exists():
            print(candidate)


if __name__ == "__main__":
    main(sys.argv[1])
