#!/usr/bin/env python3
"""Emit the manifest node JSON for a given slug."""

import json
import sys
from pathlib import Path


def main(argv) -> None:
    if len(argv) != 3:
        raise SystemExit("Usage: manifest_node_json.py MANIFEST_JSON SLUG")

    manifest_path = Path(argv[1])
    slug = argv[2]

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for node in manifest.get("nodes") or []:
        if node.get("slug") == slug:
            print(json.dumps(node))
            return

    raise SystemExit(f"Node not found for slug: {slug}")


if __name__ == "__main__":
    main(sys.argv)
