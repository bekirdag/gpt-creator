#!/usr/bin/env python3
"""Render the manifest table of contents as Markdown."""

import json
import sys
from pathlib import Path


def walk(nodes):
    lines = []
    for node in nodes:
        title = node.get("title") or ""
        label = node.get("label") or ""
        level = node.get("level", 1)
        indent = "  " * max(level - 1, 0)
        display = f"{label} {title}".strip()
        slug = node.get("slug") or ""
        if slug:
            lines.append(f"{indent}- [{display}](#{slug})")
        else:
            lines.append(f"{indent}- {display}")
    return "\n".join(lines)


def main(argv) -> None:
    if len(argv) != 3:
        raise SystemExit("Usage: write_markdown_toc.py MANIFEST_JSON OUTPUT_MD")

    manifest_path = Path(argv[1])
    out_path = Path(argv[2])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    lines = []
    lines.append("## Table of Contents")
    lines.append("")
    lines.append(walk(manifest.get("nodes") or []))
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
