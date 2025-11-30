#!/usr/bin/env python3
"""Exit with success if lib.doc_indexer.DocIndexer is importable."""

import importlib
import sys
from pathlib import Path


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("Usage: doc_indexer_ready.py PKG_ROOT")

    root = Path(argv[1])
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("lib.doc_indexer")
        getattr(module, "DocIndexer")
    except Exception:
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main(sys.argv)
