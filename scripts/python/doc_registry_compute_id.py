#!/usr/bin/env python3
"""Compute the documentation registry identifier for the provided file path."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def compute_doc_id(target: Path) -> str:
    digest = hashlib.sha256(str(target).encode("utf-8", "replace")).hexdigest().upper()
    return "DOC-" + digest[:8]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(1)

    target = Path(sys.argv[1]).resolve()
    print(compute_doc_id(target))


if __name__ == "__main__":
    main()
