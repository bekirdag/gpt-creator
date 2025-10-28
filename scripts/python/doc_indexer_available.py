#!/usr/bin/env python3
"""Probe whether lib.doc_indexer.DocIndexer is importable."""

import importlib
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(1)
    pkg_root = Path(sys.argv[1])
    sys.path.insert(0, str(pkg_root))
    try:
        module = importlib.import_module("lib.doc_indexer")
        getattr(module, "DocIndexer")
    except Exception:
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()

