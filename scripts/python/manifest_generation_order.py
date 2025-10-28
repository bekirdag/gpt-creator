#!/usr/bin/env python3
"""Print the manifest generation order slugs."""

import json
import sys
from pathlib import Path


def main(argv) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: manifest_generation_order.py MANIFEST_JSON")

    manifest_path = Path(argv[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for slug in manifest.get("generation_order") or []:
        print(slug)


if __name__ == "__main__":
    main(sys.argv)
