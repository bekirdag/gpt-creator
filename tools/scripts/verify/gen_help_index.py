#!/usr/bin/env python3
"""
Generate assets/templates/help/templates_index.json from help templates.
"""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    help_dir = repo_root / "assets" / "templates" / "help"
    index_path = help_dir / "templates_index.json"

    entries = []
    for tmpl in sorted(help_dir.glob("*_usage.txt")):
        command = tmpl.stem.replace("_usage", "").replace("_", "-")
        entries.append({"command": command, "template": str(tmpl)})

    index_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {index_path} with {len(entries)} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
