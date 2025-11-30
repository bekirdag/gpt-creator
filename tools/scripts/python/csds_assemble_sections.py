#!/usr/bin/env python3
"""Append SDS sections to the assembled document."""

import json
import sys
from pathlib import Path


def append_sections(manifest_path: Path, sections_dir: Path, out_file: Path) -> None:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes") or []
    sections_root = sections_dir

    for node in nodes:
        label_raw = node.get("label") or ""
        label = label_raw.replace(".", "-")
        slug = node.get("slug") or "section"
        filename = f"{label}_{slug}.md"
        content_path = sections_root / filename
        if not content_path.exists():
            continue
        section_text = content_path.read_text(encoding="utf-8").strip()
        if not section_text:
            continue
        with out_file.open("a", encoding="utf-8") as handle:
            handle.write(f'<a id="{slug}"></a>\n')
            handle.write(section_text)
            handle.write("\n\n")


def main() -> int:
    if len(sys.argv) != 4:
        return 1

    manifest_path = Path(sys.argv[1])
    sections_dir = Path(sys.argv[2])
    out_file = Path(sys.argv[3])
    append_sections(manifest_path, sections_dir, out_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
