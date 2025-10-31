#!/usr/bin/env python3

import os
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    real = root / "src" / "lib" / "doc_catalog.py"
    os.execv(sys.executable, [sys.executable, str(real), *sys.argv[1:]])


if __name__ == "__main__":
    main()
