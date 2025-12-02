#!/usr/bin/env python3
"""Record Codex usage wrapper (delegates to record_codex_usage_lib)."""
from __future__ import annotations

import sys
from pathlib import Path

FILE_DIR = Path(__file__).resolve().parent
if str(FILE_DIR) not in sys.path:
    sys.path.insert(0, str(FILE_DIR))

try:
    import record_codex_usage_lib as _lib
    from record_codex_usage_lib import *  # re-export for compatibility  # noqa: F401,F403
except ModuleNotFoundError as exc:
    raise SystemExit("record_codex_usage_lib.py missing from shims; rerun gpt-creator to clone helpers.") from exc

if __name__ == '__main__':
    if hasattr(_lib, 'main') and callable(getattr(_lib, 'main')):
        _lib.main()
    else:
        import importlib
        importlib.reload(_lib)
