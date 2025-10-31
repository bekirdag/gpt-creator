#!/usr/bin/env python3
import json
import sys
import unicodedata
from pathlib import Path

ALLOWED = {"plan", "changes", "commands", "notes"}


def main(path: str) -> int:
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="ignore")
    try:
        data = json.loads(raw)
    except Exception as exc:  # pragma: no cover - defensive guard
        sys.stderr.write(f"E: invalid JSON: {exc}\n")
        return 2
    if not isinstance(data, dict):
        sys.stderr.write("E: top-level must be an object\n")
        return 2

    canonical = {k: v for k, v in data.items() if k in ALLOWED and v is not None}

    changes = canonical.get("changes", [])
    if changes is None:
        changes = []
    if not isinstance(changes, list):
        sys.stderr.write("E: 'changes' must be a list\n")
        return 2
    for idx, change in enumerate(changes, 1):
        valid = False
        if isinstance(change, str) and change.startswith("--- "):
            valid = True
        elif isinstance(change, dict):
            if "path" in change and "contents" in change:
                valid = True
            elif "path" in change and "contents_path" in change:
                valid = True
            elif change.get("type") == "patch" and "patch_path" in change:
                valid = True
        if not valid:
            sys.stderr.write(f"E: invalid change at index {idx}\n")
            return 2

    serialized = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"))
    try:
        serialized.encode("ascii")
    except UnicodeEncodeError:
        serialized = (
            unicodedata.normalize("NFKD", serialized)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    p.write_text(serialized, encoding="ascii")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
