#!/usr/bin/env python3
"""Compute the output filename for a manifest node."""

import json
import sys


def main(argv) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: section_output_path.py NODE_JSON")

    node = json.loads(argv[1])
    label = (node.get("label") or "").replace(".", "-")
    slug = node.get("slug") or "section"
    print(f"{label}_{slug}.md")


if __name__ == "__main__":
    main(sys.argv)
