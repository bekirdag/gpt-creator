#!/usr/bin/env python3
"""Extract the document title for the create-pdr pipeline."""

import json
import sys
from pathlib import Path
from typing import Optional


def load_title(toc_path: Path, fallback: Optional[str]) -> str:
    try:
        data = json.loads(toc_path.read_text(encoding="utf-8"))
    except Exception:
        return fallback or "Product Requirements Document"

    title = data.get("document_title")
    if isinstance(title, str) and title.strip():
        return title
    return fallback or "Product Requirements Document"


def main() -> int:
    if len(sys.argv) < 2:
        return 1

    toc_path = Path(sys.argv[1])
    fallback = sys.argv[2] if len(sys.argv) > 2 else None
    print(load_title(toc_path, fallback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
