#!/usr/bin/env python3
"""Document index CLI wrapper (delegates to document_index_lib)."""
from __future__ import annotations

import sys
from pathlib import Path

FILE_DIR = Path(__file__).resolve().parent
if str(FILE_DIR) not in sys.path:
    sys.path.insert(0, str(FILE_DIR))

try:
    import document_index_lib as _lib
    from document_index_lib import *  # re-export for compatibility  # noqa: F401,F403
except ModuleNotFoundError as exc:
    raise SystemExit("document_index_lib.py missing from shims; rerun gpt-creator to clone helpers.") from exc


def main() -> None:
    # If the library exposes a main-like entry, use it; otherwise run the legacy module side-effects by reloading.
    if hasattr(_lib, "main") and callable(getattr(_lib, "main")):
        _lib.main()
    else:
        # Re-exec the library module to run top-level code as legacy behavior.
        import importlib
        importlib.reload(_lib)


if __name__ == "__main__":
    main()
