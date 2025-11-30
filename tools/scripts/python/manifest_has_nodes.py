#!/usr/bin/env python3
"""Check whether a manifest JSON file contains any nodes."""

import json
import sys
from pathlib import Path


def main(argv) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: manifest_has_nodes.py MANIFEST_JSON")

    manifest_path = Path(argv[1])
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes") or []
    sys.exit(0 if nodes else 1)


if __name__ == "__main__":
    main(sys.argv)
