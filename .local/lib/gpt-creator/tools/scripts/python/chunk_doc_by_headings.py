#!/usr/bin/env python3
"""Split a markdown document into chunk files based on heading structure."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def chunk_doc(source_path: Path, chunk_dir: Path, out_list: Path) -> None:
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    chunk_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[tuple[str, str, str]] = []

    heading_re = re.compile(r"^(#+)\s*(.+)$")
    current: list[str] = []
    current_heading = "Introduction"
    current_label = ""
    index = 0

    def flush() -> None:
        nonlocal index, current, current_heading, current_label
        if not current:
            return
        index += 1
        chunk_path = chunk_dir / f"chunk_{index:03d}.md"
        chunk_path.write_text("\n".join(current).strip() + "\n", encoding="utf-8")
        chunks.append((str(chunk_path), current_label, current_heading))
        current = []

    for line in lines:
        match = heading_re.match(line)
        if match:
            flush()
            heading_text = match.group(2).strip()
            label_match = re.match(r"((?:\d+\.)*\d+)", heading_text)
            current_label = label_match.group(1) if label_match else ""
            current_heading = heading_text
            current = [line]
        else:
            current.append(line)

    flush()

    if not chunks:
        chunk_path = chunk_dir / "chunk_001.md"
        chunk_path.write_text(text, encoding="utf-8")
        chunks.append((str(chunk_path), "", "Full Document"))

    out_lines = ["|".join(part.replace("\n", " ").strip() for part in chunk) for chunk in chunks]
    out_list.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 4:
        return 1
    source_path = Path(sys.argv[1])
    chunk_dir = Path(sys.argv[2])
    out_list = Path(sys.argv[3])
    chunk_doc(source_path, chunk_dir, out_list)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
