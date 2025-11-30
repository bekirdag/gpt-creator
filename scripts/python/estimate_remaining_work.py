#!/usr/bin/env python3
"""Estimate remaining work wrapper (delegates to estimate_remaining_work_lib)."""
from __future__ import annotations

import sys
from pathlib import Path

FILE_DIR = Path(__file__).resolve().parent
if str(FILE_DIR) not in sys.path:
    sys.path.insert(0, str(FILE_DIR))

import estimate_remaining_work_lib as _lib
from estimate_remaining_work_lib import *  # re-export for compatibility  # noqa: F401,F403

if __name__ == '__main__':
    if hasattr(_lib, 'main') and callable(getattr(_lib, 'main')):
        _lib.main()
    else:
        import importlib
        importlib.reload(_lib)
